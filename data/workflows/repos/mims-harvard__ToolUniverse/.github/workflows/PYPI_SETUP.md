# PyPI Auto-Publishing Setup Guide

This GitHub Action automatically builds and publishes packages to PyPI when it detects changes to the version field in `pyproject.toml`.

## Setup Instructions

### Method 1: Using PyPI API Token (Recommended for Quick Setup)

1. **Obtain PyPI API Token**
   - Visit [PyPI Account Settings](https://pypi.org/manage/account/)
   - Click "Add API token"
   - Set token name (e.g., `tooluniverse-github-actions`)
   - Select Scope as "Project: tooluniverse" (if package exists) or "Entire account" (for first-time publishing)
   - Copy the generated token (format: `pypi-...`)

2. **Add Secret to GitHub Repository**
   - Go to repository Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Name: `PYPI_API_TOKEN`
   - Value: Paste the PyPI token from the previous step
   - Click "Add secret"

### Method 2: Using PyPI Trusted Publishers (More Secure, Recommended for Production)

If using Trusted Publishers, there's no need to configure `PYPI_API_TOKEN`.

1. **Configure Trusted Publisher on PyPI**
   - Visit [PyPI Project Settings](https://pypi.org/manage/project/tooluniverse/settings/)
   - Scroll to the "Publishing" section
   - Click "Add a new publisher"
   - Fill in the following information:
     - Owner: `mims-harvard`
     - Repository name: `ToolUniverse`
     - Workflow name: `publish-pypi.yml`
     - Environment name: (leave blank)

2. **Modify Workflow File** (if using Trusted Publishers)
   - Remove the `password: ${{ secrets.PYPI_API_TOKEN }}` line from `publish-pypi.yml`
   - GitHub Action will automatically use OIDC token for authentication

## Usage

1. **Update Version Number**
   - Edit the `pyproject.toml` file
   - Change `version = "1.0.5"` to a new version (e.g., `"1.0.6"`)

2. **Commit and Push to main Branch**
   ```bash
   git add pyproject.toml
   git commit -m "Bump version to 1.0.6"
   git push origin main
   ```

3. **Automatic Publishing**
   - GitHub Action will automatically detect version changes
   - Automatically build the package
   - Automatically publish to PyPI
   - Automatically create a GitHub Release

## Verification

- Check GitHub Actions run status: `https://github.com/mims-harvard/ToolUniverse/actions`
- Check new version on PyPI: `https://pypi.org/project/tooluniverse/`
- Check GitHub Releases: `https://github.com/mims-harvard/ToolUniverse/releases`

## Important Notes

- Ensure version numbers are always incremented
- PyPI does not allow overwriting existing versions
- Follow [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`
- First-time publishing requires either manually creating the project on PyPI or using an API token with "Entire account" scope

## Troubleshooting

If publishing fails, check:
1. Is the `PYPI_API_TOKEN` secret correctly configured?
2. Does the token have sufficient permissions?
3. Is the package name already taken?
4. Does the version number comply with PEP 440 specifications?
