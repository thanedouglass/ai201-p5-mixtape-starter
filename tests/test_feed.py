"""
tests/test_feed.py — Mixtape

Tests for activity feed and friends listening now logic.
"""

from datetime import datetime, timedelta, timezone
import pytest
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now, get_activity_feed


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def feed_data(app):
    with app.app_context():
        now = datetime.now(timezone.utc)
        midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_evening = midnight_today - timedelta(hours=1)
        today_morning = midnight_today + timedelta(minutes=10)

        user = User(username="listener", email="listener@example.com")
        friend_yesterday = User(username="nightowl", email="nightowl@example.com")
        friend_today = User(username="earlybird", email="earlybird@example.com")
        db.session.add_all([user, friend_yesterday, friend_today])
        db.session.flush()

        # Establish friendships
        db.session.execute(friendships.insert().values(user_id=user.id, friend_id=friend_yesterday.id))
        db.session.execute(friendships.insert().values(user_id=friend_yesterday.id, friend_id=user.id))
        db.session.execute(friendships.insert().values(user_id=user.id, friend_id=friend_today.id))
        db.session.execute(friendships.insert().values(user_id=friend_today.id, friend_id=user.id))

        song1 = Song(title="Night Track", artist="Lunar", shared_by=user.id)
        song2 = Song(title="Morning Track", artist="Solar", shared_by=user.id)
        db.session.add_all([song1, song2])
        db.session.flush()

        # friend_yesterday listened late yesterday evening (within rolling 24h, but previous calendar day)
        event_yesterday = ListeningEvent(
            user_id=friend_yesterday.id,
            song_id=song1.id,
            listened_at=yesterday_evening,
        )
        # friend_today listened earlier today
        event_today = ListeningEvent(
            user_id=friend_today.id,
            song_id=song2.id,
            listened_at=today_morning,
        )
        db.session.add_all([event_yesterday, event_today])
        db.session.commit()

        yield {
            "user": user,
            "friend_yesterday": friend_yesterday,
            "friend_today": friend_today,
            "yesterday_evening": yesterday_evening,
            "today_morning": today_morning,
        }


def test_listening_now_excludes_yesterday(app, feed_data):
    """
    Friends who listened yesterday evening should not show in Listening Now today.
    """
    with app.app_context():
        user = feed_data["user"]
        feed = get_friends_listening_now(user.id)
        friend_names = [item["friend"]["username"] for item in feed]
        assert "nightowl" not in friend_names
        assert "earlybird" in friend_names


def test_listening_now_midnight_boundary(app, feed_data):
    """
    Events right before midnight UTC are excluded; events at or after midnight are included.
    """
    with app.app_context():
        user = feed_data["user"]
        now = datetime(2024, 6, 16, 10, 0, 0, tzinfo=timezone.utc)
        just_before_midnight = datetime(2024, 6, 15, 23, 59, 59, tzinfo=timezone.utc)
        at_midnight = datetime(2024, 6, 16, 0, 0, 0, tzinfo=timezone.utc)

        # Create two new friends
        f1 = User(username="boundary_yesterday", email="by@example.com")
        f2 = User(username="boundary_today", email="bt@example.com")
        db.session.add_all([f1, f2])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=user.id, friend_id=f1.id))
        db.session.execute(friendships.insert().values(user_id=user.id, friend_id=f2.id))

        song = Song(title="Boundary Song", artist="Edge", shared_by=user.id)
        db.session.add(song)
        db.session.flush()

        db.session.add(ListeningEvent(user_id=f1.id, song_id=song.id, listened_at=just_before_midnight))
        db.session.add(ListeningEvent(user_id=f2.id, song_id=song.id, listened_at=at_midnight))
        db.session.commit()

        feed = get_friends_listening_now(user.id, now=now)
        friend_names = [item["friend"]["username"] for item in feed]
        assert "boundary_yesterday" not in friend_names
        assert "boundary_today" in friend_names


def test_listening_now_deduplicates_per_friend(app, feed_data):
    """
    If a friend listened multiple times today, only their most recent listen is returned.
    """
    with app.app_context():
        user = feed_data["user"]
        friend = feed_data["friend_today"]
        now = datetime.now(timezone.utc)

        song_later = Song(title="Later Track", artist="Noon", shared_by=user.id)
        db.session.add(song_later)
        db.session.flush()

        # Add a later listen today for friend_today
        event_later = ListeningEvent(
            user_id=friend.id,
            song_id=song_later.id,
            listened_at=now,
        )
        db.session.add(event_later)
        db.session.commit()

        feed = get_friends_listening_now(user.id)
        matching = [item for item in feed if item["friend"]["username"] == friend.username]
        assert len(matching) == 1
        assert matching[0]["song"]["title"] == "Later Track"


def test_activity_feed_includes_past_days(app, feed_data):
    """
    General activity feed is not restricted to the current calendar day.
    """
    with app.app_context():
        user = feed_data["user"]
        feed = get_activity_feed(user.id)
        friend_names = [item["friend"]["username"] for item in feed]
        assert "nightowl" in friend_names
        assert "earlybird" in friend_names
