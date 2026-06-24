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
    Return the configured AJO path for an ACC field, or None if not in config.
    Callers that get None should use the raw field name as-is (bracket-only conversion)
    so the user sees it clearly and can edit it in the analysis UI.
    """
    return RECIPIENT_MAPPINGS.get(acc_field)
