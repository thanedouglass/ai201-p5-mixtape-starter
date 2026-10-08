"""
tests/test_notifications.py — Mixtape

Tests for notification creation and retrieval logic.
"""

import pytest
from app import create_app, db
from models import User, Song, Notification
from services.notification_service import (
    rate_song,
    get_notifications,
    mark_as_read,
)


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def notification_data(app):
    with app.app_context():
        sharer = User(username="sharer", email="sharer@example.com")
        rater = User(username="rater", email="rater@example.com")
        db.session.add_all([sharer, rater])
        db.session.flush()

        song = Song(title="Sunset Boulevard", artist="City Lights", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()

        yield {
            "sharer": sharer,
            "rater": rater,
            "song": song,
        }


def test_rate_song_creates_notification_for_owner(app, notification_data):
    """
    When a user rates a song, a notification should be created for the song owner.
    """
    with app.app_context():
        sharer = notification_data["sharer"]
        rater = notification_data["rater"]
        song = notification_data["song"]

        # Friend rates the song
        rating = rate_song(user_id=rater.id, song_id=song.id, score=5)
        assert rating.score == 5

        # Check notifications for the song sharer
        notifications = get_notifications(sharer.id)
        assert len(notifications) == 1
        assert notifications[0]["type"] == "song_rated"
        assert "rater" in notifications[0]["body"]
        assert "Sunset Boulevard" in notifications[0]["body"]
        assert "5 stars" in notifications[0]["body"]


def test_rate_own_song_does_not_create_notification(app, notification_data):
    """
    Rating one's own shared song should not trigger a notification.
    """
    with app.app_context():
        sharer = notification_data["sharer"]
        song = notification_data["song"]

        rate_song(user_id=sharer.id, song_id=song.id, score=4)
        notifications = get_notifications(sharer.id)
        assert len(notifications) == 0


def test_invalid_score_raises_value_error(app, notification_data):
    """
    Invalid scores should raise ValueError without persisting ratings or notifications.
    """
    with app.app_context():
        sharer = notification_data["sharer"]
        rater = notification_data["rater"]
        song = notification_data["song"]

        with pytest.raises(ValueError, match="Score must be between 1 and 5"):
            rate_song(user_id=rater.id, song_id=song.id, score=6)

        assert len(get_notifications(sharer.id)) == 0


def test_get_notifications_unread_filter_and_mark_as_read(app, notification_data):
    """
    Notifications can be filtered by unread status and marked as read.
    """
    with app.app_context():
        sharer = notification_data["sharer"]
        rater = notification_data["rater"]
        song = notification_data["song"]

        rate_song(user_id=rater.id, song_id=song.id, score=4)
        unread = get_notifications(sharer.id, unread_only=True)
        assert len(unread) == 1

        mark_as_read(unread[0]["id"])
        unread_after = get_notifications(sharer.id, unread_only=True)
        assert len(unread_after) == 0

        all_notifs = get_notifications(sharer.id, unread_only=False)
        assert len(all_notifs) == 1
        assert all_notifs[0]["read"] is True


def test_rating_update_by_friend_notifies_owner(app, notification_data):
    """
    Updating an existing rating also sends an updated notification to the song owner.
    """
    with app.app_context():
        sharer = notification_data["sharer"]
        rater = notification_data["rater"]
        song = notification_data["song"]

        rate_song(user_id=rater.id, song_id=song.id, score=3)
        rate_song(user_id=rater.id, song_id=song.id, score=5)

        notifications = get_notifications(sharer.id)
        assert len(notifications) == 2
        assert notifications[0]["body"] == f"{rater.username} rated your song '{song.title}' 5 stars."

