RECIPIENT_MAPPINGS: dict[str, str] = {
    "recipient.firstName":      "profile.person.name.firstName",
    "recipient.lastName":       "profile.person.name.lastName",
    "recipient.email":          "profile.workEmail.address",
    "recipient.phone":          "profile.mobilePhone.number",
    "recipient.mobilePhone":    "profile.mobilePhone.number",
    "recipient.gender":         "profile.person.gender",
    "recipient.birthDate":      "profile.person.birthDate",
    "recipient.language":       "profile.preferredLanguage",
}


def get_ajo_mapping(acc_field: str) -> str | None:
    """
    Map an ACC placeholder field name to its AJO equivalent.

    recipient.x  → RECIPIENT_MAPPINGS lookup, else profile.x
    targetData.x → context.targetData.x
    anything else → None (caller decides how to handle)
    """
    if acc_field in RECIPIENT_MAPPINGS:
        return RECIPIENT_MAPPINGS[acc_field]
    if acc_field.startswith("recipient."):
        suffix = acc_field[len("recipient."):]
        return f"profile.{suffix}"
    if acc_field.startswith("targetData."):
        return f"context.{acc_field}"
    return None
