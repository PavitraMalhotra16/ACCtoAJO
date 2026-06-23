"""
Mapping of ACC personalization fields (<%=...%>) to AJO profile/context field equivalents.
Used during template transformation to replace ACC-specific tokens with AJO-compatible ones.
"""

FIELD_MAPPING = {
  "recipient.firstName": "profile.person.name.firstName",
  "recipient.lastName": "profile.person.name.lastName",
  "recipient.name": "profile.person.name.fullName",
  "recipient.middleName": "profile.person.name.middleName",
  "recipient.salutation": "profile.person.name.courtesyTitle",
  "recipient.suffix": "profile.person.name.suffix",
  "recipient.gender": "profile.person.gender",
  "recipient.birthDate": "profile.person.birthDate",
  "recipient.email": "profile.personalEmail.address",
  "recipient.personalEmail": "profile.personalEmail.address",
  "recipient.workEmail": "profile.workEmail.address",
  "recipient.mobilePhone": "profile.mobilePhone.number",
  "recipient.homePhone": "profile.homePhone.number",
  "recipient.workPhone": "profile.workPhone.number",
  "recipient.fax": "profile.faxPhone.number",
  "recipient.address1": "profile.homeAddress.street1",
  "recipient.address2": "profile.homeAddress.street2",
  "recipient.address3": "profile.homeAddress.street3",
  "recipient.address4": "profile.homeAddress.street4",
  "recipient.city": "profile.homeAddress.city",
  "recipient.state": "profile.homeAddress.stateProvince",
  "recipient.postalCode": "profile.homeAddress.postalCode",
  "recipient.zipCode": "profile.homeAddress.postalCode",
  "recipient.country": "profile.homeAddress.country",
  "recipient.countryCode": "profile.homeAddress.countryCode",
  "recipient.region": "profile.homeAddress.region",
  "recipient.company": "profile.organizations",
  "recipient.organization": "profile.organizations",
  "targetData.changeType": "context.changeType",
  "targetData.effectiveDate": "context.effectiveDate",
  "targetData.manageSubscriptionURL": "context.manageSubscriptionURL",
  "targetData.planName": "context.planName"
}
