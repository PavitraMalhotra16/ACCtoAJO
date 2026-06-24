from pipeline.placeholder_config import get_ajo_mapping


def test_known_recipient_field():
    assert get_ajo_mapping("recipient.firstName") == "profile.person.name.firstName"


def test_unknown_recipient_field_gets_profile_prefix():
    assert get_ajo_mapping("recipient.customField") == "profile.customField"


def test_target_data_field_gets_context_prefix():
    assert get_ajo_mapping("targetData.orderId") == "context.targetData.orderId"


def test_unknown_prefix_returns_none():
    assert get_ajo_mapping("delivery.something") is None
