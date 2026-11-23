"""Google client options for hosted and application-default identities."""
import json
import os


def client_options():
    options = {"project": os.environ["GOOGLE_CLOUD_PROJECT"]}
    account = os.getenv("LABLINK_GOOGLE_CREDENTIALS_JSON")
    if account:
        from google.oauth2 import service_account

        options["credentials"] = service_account.Credentials.from_service_account_info(
            json.loads(account), scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    return options
