How to test this in CI
==============================================================================
1. Create two AWS S3 buckets in the same region in your AWS Account.
    - ``${aws_account_id}-us-east-1-s3pathlib-test``, don't turn on versioning.
    - ``${aws_account_id}-us-east-1-s3pathlib-test-versioning-on``, turn on versioning
2. Create an IAM user with the permissions defined in ``iam-policy.json``.
3. Create an access key for the IAM user. And set these two GitHub Action secrets:
    - ``AWS_ACCESS_KEY_ID_FOR_GITHUB_CI``
    - ``AWS_SECRET_ACCESS_KEY_FOR_GITHUB_CI``
