# tests/test_messages.py
import json
from pathlib import Path
from receptionist.messages import save_message, Message


def test_save_message_creates_file(tmp_path):
    msg = Message(
        caller_name="John Doe",
        callback_number="+15559876543",
        message="Please call me back about my appointment.",
        business_name="Test Dental",
    )
    save_message(msg, delivery="file", file_path=str(tmp_path))

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1

    data = json.loads(files[0].read_text())
    assert data["caller_name"] == "John Doe"
    assert data["callback_number"] == "+15559876543"
    assert data["message"] == "Please call me back about my appointment."
    assert data["business_name"] == "Test Dental"
    assert "timestamp" in data


def test_save_multiple_messages(tmp_path):
    for i in range(3):
        msg = Message(
            caller_name=f"Caller {i}",
            callback_number=f"+1555000000{i}",
            message=f"Message {i}",
            business_name="Test Dental",
        )
        save_message(msg, delivery="file", file_path=str(tmp_path))

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 3


def test_save_message_creates_directory(tmp_path):
    nested = tmp_path / "sub" / "dir"
    msg = Message(
        caller_name="Jane",
        callback_number="+15551111111",
        message="Test",
        business_name="Test Dental",
    )
    save_message(msg, delivery="file", file_path=str(nested))
    assert nested.exists()
    assert len(list(nested.glob("*.json"))) == 1
