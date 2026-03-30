# GitHub Actions Workflows

This directory contains GitHub Actions workflows for CI/CD automation.

## Platform-Specific Test Workflows

Each platform has its own dedicated workflow for independent testing and badge status:

- **`test-win.yml`** - Windows x64 tests
- **`test-linux-x86.yml`** - Linux x86_64 tests
- **`test-linux-arm.yml`** - Linux ARM64 tests
- **`test-macos-x86.yml`** - macOS x86_64 (Intel) tests
- **`test-macos-arm.yml`** - macOS ARM64 (Apple Silicon) tests

Each workflow:
- Runs on push to main/develop, pull requests, and manual dispatch
- Tests automatic toolchain download and installation
- Verifies C and C++ compilation
- Runs integration tests
- Provides individual build status badge

## Available Workflows

### 1. `test.yml` - Main Test Suite
**Triggers:** Push to main/develop, pull requests, manual dispatch

**Jobs:**
- **unit-tests**: Runs unit tests across multiple platforms and Python versions
  - Platforms: Windows x64, Linux x64, macOS x64 (Intel), macOS ARM64 (Apple Silicon)
  - Python versions: 3.10, 3.11, 3.12
  - Total combinations: 12 test runs (4 platforms × 3 Python versions)

- **integration-tests**: Tests actual toolchain download and compilation
  - Platforms: Windows x64, Linux x64, Linux ARM64, macOS x64, macOS ARM64
  - Tests automatic download, installation, and basic compilation

- **lint**: Code quality checks (runs on Ubuntu only)
  - ruff (linter and formatter), mypy, pyright

### 2. `lint.yml` - Code Quality
**Triggers:** Push to main/develop, pull requests, manual dispatch

Runs all code quality tools:
- ruff (linter and formatter)
- mypy (type checking)

### 3. `release.yml` (if exists)
Release automation workflow.

## Platform Coverage

### GitHub Actions Runners Used

| Platform | OS Runner | Architecture | Notes |
|----------|-----------|--------------|-------|
| Windows | `windows-latest` | x86_64 | Windows Server 2022 |
| Linux x64 | `ubuntu-latest` | x86_64 | Ubuntu 22.04 LTS |
| Linux ARM64 | `ubuntu-24.04-arm` | ARM64 | Ubuntu 24.04 on ARM |
| macOS Intel | `macos-15-intel` | x86_64 | macOS 15 (Sequoia) Intel |
| macOS Apple Silicon | `macos-14` | ARM64 | macOS 14 (Sonoma) M1/M2 |

## Test Strategy

### Unit Tests (`test.yml`)
- Fast, focused tests
- Tests code logic without downloading toolchain
- Runs on multiple Python versions to ensure compatibility
- Includes linting and type checking

### Integration Tests (`test.yml`)
- Downloads actual LLVM toolchain via manifest system
- Tests end-to-end workflow
- Verifies platform-specific binary execution
- Single Python version (3.11) to save CI time

### Platform Tests (`platform-tests.yml`)
- Most comprehensive testing
- Deep dive into each platform
- Tests all wrapper commands
- Multiple compilation scenarios
- Runs daily to catch platform regressions

## Running Workflows Locally

### Using `act` (GitHub Actions local runner)
```bash
# Install act
# See: https://github.com/nektos/act

# Run platform tests
act -j platform-matrix

# Run specific platform
act -j platform-matrix --matrix platform:linux --matrix arch:x86_64

# Run unit tests
act -j unit-tests
```

### Manual Testing
```bash
# Run the same tests as CI locally
./test                    # Run all tests
./lint                    # Run linters

# Test specific platform functionality
uv run pytest tests/test_integration.py -v

# Test CLI commands
uv run clang-tool-chain info
uv run clang-tool-chain-c --version
```

## Workflow Optimization

### Caching Strategy
- uv handles Python dependency caching automatically
- Toolchain binaries are cached in `~/.clang-tool-chain/` between test steps
- First download takes ~1-5 minutes depending on platform
- Subsequent runs reuse installed toolchain

### Parallel Execution
- All platform tests run in parallel
- `fail-fast: false` ensures all platforms are tested even if one fails
- Separate job for each platform combination

### Timeout Limits
- Download/install: 15-20 minutes
- Compilation tests: 5 minutes
- Integration tests: 10 minutes

## Adding New Platform Tests

To add a new platform:

1. Add entry to `matrix.include` in `platform-tests.yml`:
```yaml
- os: <runner-name>
  platform: <win|linux|darwin>
  arch: <x86_64|arm64>
  python: '3.11'
```

2. Ensure manifest exists for the platform in `downloads-bins/assets/clang/manifest.json`

3. Test locally if possible, or push to a feature branch and verify CI

## Troubleshooting

### Common Issues

**ARM64 runner not available:**
- Linux ARM64 requires GitHub Enterprise or specific runner setup
- Check GitHub Actions runner availability: https://github.com/actions/runner-images

**Download timeouts:**
- Increase `timeout-minutes` in download steps
- Check GitHub raw content availability
- Verify manifest URLs are accessible

**Platform detection failures:**
- Check `platform.system()` and `platform.machine()` output in logs
- Verify normalization logic in `wrapper.py`

**Compilation failures:**
- Check toolchain installation completed successfully
- Verify binary permissions on Unix systems
- Check PATH and environment variables

## Best Practices

1. **Test on all platforms before merge:** Use the workflow dispatch trigger to manually run tests
2. **Monitor daily runs:** Check scheduled test runs for platform regressions
3. **Keep dependencies updated:** Regularly update Python and GitHub Actions versions
4. **Document platform-specific quirks:** Add notes to this file for platform issues

## CI Status Badges

Platform-specific badges (currently in README.md):

```markdown
[![Linting](../../actions/workflows/lint.yml/badge.svg)](../../actions/workflows/lint.yml)
[![win](../../actions/workflows/test-win.yml/badge.svg)](../../actions/workflows/test-win.yml)
[![linux-x86](../../actions/workflows/test-linux-x86.yml/badge.svg)](../../actions/workflows/test-linux-x86.yml)
[![linux-arm](../../actions/workflows/test-linux-arm.yml/badge.svg)](../../actions/workflows/test-linux-arm.yml)
[![macos-x86](../../actions/workflows/test-macos-x86.yml/badge.svg)](../../actions/workflows/test-macos-x86.yml)
[![macos-arm](../../actions/workflows/test-macos-arm.yml/badge.svg)](../../actions/workflows/test-macos-arm.yml)
```

Or with full URLs:

```markdown
[![win](https://github.com/zackees/clang-tool-chain/actions/workflows/test-win.yml/badge.svg)](https://github.com/zackees/clang-tool-chain/actions/workflows/test-win.yml)
[![linux-x86](https://github.com/zackees/clang-tool-chain/actions/workflows/test-linux-x86.yml/badge.svg)](https://github.com/zackees/clang-tool-chain/actions/workflows/test-linux-x86.yml)
[![linux-arm](https://github.com/zackees/clang-tool-chain/actions/workflows/test-linux-arm.yml/badge.svg)](https://github.com/zackees/clang-tool-chain/actions/workflows/test-linux-arm.yml)
[![macos-x86](https://github.com/zackees/clang-tool-chain/actions/workflows/test-macos-x86.yml/badge.svg)](https://github.com/zackees/clang-tool-chain/actions/workflows/test-macos-x86.yml)
[![macos-arm](https://github.com/zackees/clang-tool-chain/actions/workflows/test-macos-arm.yml/badge.svg)](https://github.com/zackees/clang-tool-chain/actions/workflows/test-macos-arm.yml)
```
