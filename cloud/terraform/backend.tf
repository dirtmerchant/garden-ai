terraform {
  backend "gcs" {
    # Configured via CLI: terraform init -backend-config="bucket=$TFSTATE_BUCKET" -backend-config="prefix=$TFSTATE_PREFIX"
    # See .env.example for values.
  }
}
