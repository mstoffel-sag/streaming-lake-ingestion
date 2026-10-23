#!/usr/bin/env bash
# Creates the S3 bucket (if missing) and the IAM role Cumulocity Streaming Lake Ingestion
# assumes to reach your own data lake.
# Docs: .../datahub/streaming-lake-ingestion/#own-data-lake

set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --bucket NAME --region REGION --principal ARN [options]

Required:
  -b, --bucket NAME        S3 bucket (created if missing)
  -r, --region REGION      bucket region, as shown on the Cumulocity Data Lake setup page
  -p, --principal ARN      base principal ARN shown on the Cumulocity Data Lake setup page

Optional:
  -x, --prefix PREFIX      key prefix in the bucket (default: c8y) -> s3://BUCKET/PREFIX
  -s, --suffix SUFFIX      role name = c8y-streaming-lake-ingestion-SUFFIX (default: default)
  -e, --external-id ID     32+ chars of [A-Za-z0-9_+=,.@:/-], unique per tenant
                           (generated if omitted)
      --profile NAME       AWS CLI profile
  -h, --help               show this help
EOF
}

BUCKET="" REGION="" BASE_PRINCIPAL_ARN="" EXTERNAL_ID="" PROFILE=""
PREFIX="c8y" ROLE_SUFFIX="default"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -b|--bucket)      BUCKET="${2:?missing value for $1}"; shift 2 ;;
    -r|--region)      REGION="${2:?missing value for $1}"; shift 2 ;;
    -p|--principal)   BASE_PRINCIPAL_ARN="${2:?missing value for $1}"; shift 2 ;;
    -x|--prefix)      PREFIX="${2:?missing value for $1}"; shift 2 ;;
    -s|--suffix)      ROLE_SUFFIX="${2:?missing value for $1}"; shift 2 ;;
    -e|--external-id) EXTERNAL_ID="${2:?missing value for $1}"; shift 2 ;;
    --profile)        PROFILE="${2:?missing value for $1}"; shift 2 ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

missing=()
[[ -z "$BUCKET" ]] && missing+=(--bucket)
[[ -z "$REGION" ]] && missing+=(--region)
[[ -z "$BASE_PRINCIPAL_ARN" ]] && missing+=(--principal)
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Missing required: ${missing[*]}" >&2; usage >&2; exit 1
fi

[[ -n "$PROFILE" ]] && export AWS_PROFILE="$PROFILE"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"

PREFIX="${PREFIX#/}"; PREFIX="${PREFIX%/}"
[[ -z "$PREFIX" ]] && { echo "--prefix must not be empty" >&2; exit 1; }
ROLE_NAME="c8y-streaming-lake-ingestion-${ROLE_SUFFIX}"
POLICY_NAME="c8y-streaming-lake-ingestion"

if [[ -z "$EXTERNAL_ID" ]]; then
  # tr dies of SIGPIPE once head has enough; under pipefail that would abort the script.
  EXTERNAL_ID="c8y-$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40 || true)"
  GENERATED=1
fi
if [[ ${#EXTERNAL_ID} -lt 32 || ! "$EXTERNAL_ID" =~ ^[A-Za-z0-9_+=,.@:/-]+$ ]]; then
  echo "External ID must be >= 32 chars from [A-Za-z0-9_+=,.@:/-]" >&2; exit 1
fi

# Create the bucket if it is missing.
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "Bucket $BUCKET exists - skipping creation"
else
  echo "Creating bucket $BUCKET in $REGION"
  aws s3 mb "s3://$BUCKET" --region "$REGION"
fi

# Versioning lets Iceberg recover metadata overwritten by a failed commit.
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
BUCKET_REGION=$(aws s3api get-bucket-location --bucket "$BUCKET" \
  --query 'LocationConstraint' --output text)
[[ "$BUCKET_REGION" == "None" ]] && BUCKET_REGION=us-east-1
if [[ "$BUCKET_REGION" != "$REGION" ]]; then
  echo "Bucket $BUCKET is in $BUCKET_REGION, not $REGION - it cannot be moved" >&2; exit 1
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/trust-policy.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "${BASE_PRINCIPAL_ARN}" },
      "Action": "sts:AssumeRole",
      "Condition": { "StringEquals": { "sts:ExternalId": "${EXTERNAL_ID}" } }
    }
  ]
}
EOF

cat > "$WORK/s3-policy.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LocateBucket",
      "Effect": "Allow",
      "Action": ["s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::${BUCKET}"
    },
    {
      "Sid": "ListPrefix",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::${BUCKET}",
      "Condition": { "StringLike": { "s3:prefix": ["${PREFIX}", "${PREFIX}/*"] } }
    },
    {
      "Sid": "ObjectReadWrite",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::${BUCKET}/${PREFIX}/*"
    }
  ]
}
EOF

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "Role $ROLE_NAME exists - updating trust policy"
  aws iam update-assume-role-policy --role-name "$ROLE_NAME" \
    --policy-document "file://$WORK/trust-policy.json"
else
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$WORK/trust-policy.json" >/dev/null
fi

aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" --policy-document "file://$WORK/s3-policy.json"

ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)

cat <<EOF

Done. Enter these in Cumulocity > Administration > Settings > Data Lake:

  Role ARN     : ${ROLE_ARN}
  External ID  : ${EXTERNAL_ID}${GENERATED:+   (generated - keep a record of it)}
  Bucket       : ${BUCKET}  (region ${BUCKET_REGION})
  Prefix       : ${PREFIX}
  Base location: s3://${BUCKET}/${PREFIX}

Note: a customer-managed KMS key on the bucket is not supported; use S3 default encryption.
EOF
