# Define secrets in AWS Secrets Manager to securely store credentials.
# These secrets will be populated manually with the contents of your JSON files.
resource "aws_secretsmanager_secret" "checkfront_credentials" {
  name = "checkfront_credentials"
  description = "Checkfront API key and secret."
}

resource "aws_secretsmanager_secret" "google_credentials" {
  name = "google_credentials"
  description = "Google API credentials (from google_credentials.json)."
}

resource "aws_secretsmanager_secret" "google_token" {
  name = "google_token"
  description = "Google API token (from token.json)."
}

resource "aws_secretsmanager_secret" "site_configuration" {
  name = "site_configuration"
  description = "Configuration for site mappings, iCal URLs, etc."
}
