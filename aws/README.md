# Cross-Account S3 Access for Databricks

This guide outlines the steps to grant a Databricks workspace in Account B read-only access to an S3 bucket in Account A using IAM Role Assumption (`sts:AssumeRole`) and Instance Profiles.

## Prerequisites

- AWS CLI installed and configured.
- Credentials for Account A (Bucket Owner).
- Credentials for Account B (Databricks Owner - Account ID: 619071352531).
- Replace `<Account_A_ID>` with your actual 12-digit Account A ID before running the commands.

## Part 1: Configure Account A (The Bucket Owner)

Ensure your AWS CLI profile is set to Account A.

### 1. Create the Trust Policy File

Create `trust-policy-a.json` to allow Account B to assume the role.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::619071352531:root"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### 2. Create the Cross-Account Role

```bash
aws iam create-role \
    --role-name CrossAccountS3ReadRole \
    --assume-role-policy-document file://trust-policy-a.json
```

### 3. Create the S3 Read-Only Permissions File

Create `permissions-policy-a.json` for bucket access.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::cumulocity-trial-prod-iceflow-bucket"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::cumulocity-trial-prod-iceflow-bucket/*"
    }
  ]
}
```

### 4. Attach Permissions to the Role

```bash
aws iam put-role-policy \
    --role-name CrossAccountS3ReadRole \
    --policy-name S3ReadOnlyAccess \
    --policy-document file://permissions-policy-a.json
```

## Part 2: Configure Account B (The Databricks Environment)

Ensure your AWS CLI profile is set to Account B.

### 1. Create the EC2 Trust Policy File

Create `ec2-trust-policy-b.json` so EC2 instances can assume this role.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### 2. Create the Databricks EC2 Role

```bash
aws iam create-role \
    --role-name DatabricksS3AccessRole \
    --assume-role-policy-document file://ec2-trust-policy-b.json
```

### 3. Create the Assume Role Permissions File

Create `assume-role-policy-b.json` to allow assumption of Account A's role.
(Make sure to update `<Account_A_ID>`)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::<Account_A_ID>:role/CrossAccountS3ReadRole"
    }
  ]
}
```

### 4. Attach Assume Role Permissions

```bash
aws iam put-role-policy \
    --role-name DatabricksS3AccessRole \
    --policy-name AssumeAccountARole \
    --policy-document file://assume-role-policy-b.json
```

### 5. Create and Bind the Instance Profile

```bash
aws iam create-instance-profile \
    --instance-profile-name DatabricksS3AccessProfile

aws iam add-role-to-instance-profile \
    --instance-profile-name DatabricksS3AccessProfile \
    --role-name DatabricksS3AccessRole
```

## Part 3: Configure Compute Role Permissions (Resolving PassRole Issues)

The Databricks compute role must be allowed to attach the new instance profile to its EC2 nodes.

### 1. Create the PassRole Policy File

Create `passrole-policy.json`.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": "arn:aws:iam::619071352531:role/DatabricksS3AccessRole"
        }
    ]
}
```

### 2. Attach PassRole to Databricks Compute Role

```bash
aws iam put-role-policy \
    --role-name databricks-compute-role-7474658771719951 \
    --policy-name AllowPassDatabricksS3AccessRole \
    --policy-document file://passrole-policy.json
```

## Part 4: Resolve Permissions Boundary Restrictions

If the previous step fails verification due to a Permissions Boundary, the boundary policy itself must be updated to allow the `iam:PassRole` action. Because the default boundary is often an AWS Managed Policy, you must clone it.

### 1. Clone the Existing Boundary Policy (Console Recommended)

1. Log into the AWS Console for Account B.
2. Navigate to **IAM > Roles** -> `databricks-compute-role-7474658771719951`.
3. Copy the JSON of the current Permissions Boundary.

### 2. Create a Custom Boundary Policy

Create `custom-boundary.json` containing the original boundary's JSON, but append this to the `"Statement"` array:

```json
{
    "Effect": "Allow",
    "Action": "iam:PassRole",
    "Resource": "arn:aws:iam::619071352531:role/DatabricksS3AccessRole"
}
```

### 3. Apply the Custom Boundary via CLI

```bash
# Create the new custom policy
aws iam create-policy \
    --policy-name CustomDatabricksComputeBoundary \
    --policy-document file://custom-boundary.json

# Update the compute role to use the new boundary
aws iam put-role-permissions-boundary \
    --role-name databricks-compute-role-7474658771719951 \
    --permissions-boundary arn:aws:iam::619071352531:policy/CustomDatabricksComputeBoundary
```

## Part 5: Databricks Cluster Configuration

Once the Instance Profile `DatabricksS3AccessProfile` is verified and added to your cluster in the Databricks UI, add the following to your cluster's **Advanced > Spark Config** before starting it:

```
fs.s3a.aws.credentials.provider org.apache.hadoop.fs.s3a.auth.AssumedRoleCredentialProvider
fs.s3a.assumed.role.arn arn:aws:iam::<Account_A_ID>:role/CrossAccountS3ReadRole
fs.s3a.assumed.role.session.name DatabricksCrossAccountRead
```