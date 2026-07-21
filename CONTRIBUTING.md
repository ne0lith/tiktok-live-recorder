<!-- omit in toc -->
# Contributing to TikTok Live Recorder

First off, thanks for taking the time to contribute!

All types of contributions are encouraged and valued. See the [Table of Contents](#table-of-contents) for different ways to help and details about how this project handles them. Please make sure to read the relevant section before making your contribution.

> And if you like the project, but just don't have time to contribute, that's fine. There are other easy ways to support the project:
> - Star the project
> - Share it with others who might find it useful
> - Report bugs or suggest improvements via issues

<!-- omit in toc -->
## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [I Have a Question](#i-have-a-question)
- [I Want To Contribute](#i-want-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Your First Code Contribution](#your-first-code-contribution)
  - [Pull Request Workflow](#pull-request-workflow)
  - [Improving The Documentation](#improving-the-documentation)
- [Styleguides](#styleguides)
  - [Commit Messages](#commit-messages)

## Code of Conduct

This project and everyone participating in it is governed by the
[TikTok Live Recorder Code of Conduct](./CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.

Report Code of Conduct violations privately - not in public issues. See [SECURITY.md](./SECURITY.md).

## I Have a Question

> If you want to ask a question, we assume that you have read the available [Documentation](./README.md).

Before you ask a question, search existing [Issues](https://github.com/ne0lith/tiktok-live-recorder/issues) that might help you. If you still need clarification:

- Open an [Issue](https://github.com/ne0lith/tiktok-live-recorder/issues/new/choose) using the appropriate template.
- Provide as much context as you can about what you're running into.
- Include project and platform versions (Python, FFmpeg, OS), depending on what seems relevant.

## I Want To Contribute

> ### Legal Notice <!-- omit in toc -->
> When contributing to this project, you must agree that you have authored 100% of the content, that you have the necessary rights to the content and that the content you contribute may be provided under the project licence.

### Reporting Bugs

<!-- omit in toc -->
#### Before Submitting a Bug Report

A good bug report shouldn't leave others needing to chase you up for more information. Please:

- Make sure that you are using the latest version.
- Determine if your bug is really a bug and not an error on your side (e.g. incompatible environment components/versions). Make sure you have read the [documentation](./README.md).
- Search existing [issues](https://github.com/ne0lith/tiktok-live-recorder/issues?q=label%3Abug) for duplicates.
- Collect information about the bug:
  - Stack trace (Traceback)
  - OS, platform, and version (Windows, Linux, macOS, x86, ARM)
  - Python version, FFmpeg version, and package manager (`uv`)
  - The command you ran and the output you received
  - Whether you can reliably reproduce the issue

<!-- omit in toc -->
#### How Do I Submit a Good Bug Report?

> You must never report security related issues, vulnerabilities or bugs including sensitive information to the issue tracker, or elsewhere in public. Instead, see [SECURITY.md](./SECURITY.md).

Use the [bug report template](https://github.com/ne0lith/tiktok-live-recorder/issues/new?template=bug_report.yml) when filing an issue.

Once it's filed:

- The project team will label the issue accordingly.
- A maintainer will try to reproduce the issue with your provided steps. If there are no reproduction steps or no obvious way to reproduce the issue, the team will ask you for those steps and mark the issue as `needs-repro`.
- If the team is able to reproduce the issue, it will be marked `needs-fix` and left for implementation.

### Suggesting Enhancements

This section guides you through submitting an enhancement suggestion for TikTok Live Recorder, **including completely new features and minor improvements to existing functionality**.

<!-- omit in toc -->
#### Before Submitting an Enhancement

- Make sure that you are using the latest version.
- Read the [documentation](./README.md) carefully and find out if the functionality is already covered.
- Perform a [search](https://github.com/ne0lith/tiktok-live-recorder/issues) to see if the enhancement has already been suggested.
- Find out whether your idea fits with the scope and aims of the project.

<!-- omit in toc -->
#### How Do I Submit a Good Enhancement Suggestion?

Use the [feature request template](https://github.com/ne0lith/tiktok-live-recorder/issues/new?template=feature_request.yml).

- Use a **clear and descriptive title** for the issue.
- Provide a **step-by-step description of the suggested enhancement**.
- **Describe the current behavior** and **explain which behavior you expected to see instead** and why.
- **Explain why this enhancement would be useful** to most TikTok Live Recorder users.

### Your First Code Contribution

**Prerequisites:** [Git](https://git-scm.com), [Python 3.11+](https://www.python.org/downloads/), [FFmpeg](https://ffmpeg.org/download.html), [uv](https://docs.astral.sh/uv/getting-started/installation/)

1. Fork [ne0lith/tiktok-live-recorder](https://github.com/ne0lith/tiktok-live-recorder) and clone it locally:
   ```bash
   git clone https://github.com/<your-fork>/tiktok-live-recorder
   cd tiktok-live-recorder
   ```

2. Install all dependencies including dev tools:
   ```bash
   uv sync --extra dev
   ```

3. Install pre-commit hooks:
   ```bash
   uv run pre-commit install
   ```

4. Create a branch for your change:
   ```bash
   git checkout -b feat/your-feature-name
   ```

5. Run the tool locally and the test suite:
   ```bash
   uv run python src/main.py -h
   uv run pytest
   ```

6. Before submitting, ensure code is formatted and linted:
   ```bash
   uv run ruff format .
   uv run ruff check .
   ```

### Pull Request Workflow

1. Fork the repository and create a feature branch from `main`.
2. Make your changes with tests where applicable.
3. Run the full test suite and linters locally (see above).
4. Add a `CHANGELOG.md` entry under `[Unreleased]` if the change is user-facing.
5. Open a pull request against `main` using the PR template.
6. Ensure CI passes:
   - **Pytest** - unit tests on Ubuntu
   - **Ruff** - format and lint checks
   - **Installation Test** - smoke test on Ubuntu, Windows, and macOS

Keep third-party GitHub Actions on Node 24-compatible releases to avoid deprecation warnings from GitHub-hosted runners.

### Improving The Documentation

Documentation lives in:
- `README.md` - installation and usage overview
- `CHANGELOG.md` - release notes ([Keep a Changelog](https://keepachangelog.com/) format)
- `docs/GUIDE.md` - detailed guides (cookies, watchlist, room_id, Telegram, config)
- `config/` - user configuration (`cookies.json`, `users.json`, `telegram.json`; see `*.example` templates)
- `SECURITY.md` - security policy and private reporting
- `CONTRIBUTING.md` - this file

## Styleguides

### Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>: <short summary>
```

Common types: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`.

<!-- omit in toc -->
## Attribution
This guide is based on the [contributing.md](https://contributing.md/generator) template.
