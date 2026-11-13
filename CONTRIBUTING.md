
# Contributing to PokeMatrix

Thanks for your interest in contributing to PokeMatrix!

PokeMatrix is a Matrix-based adaptation of Pokétwo. The goal is to preserve the original game's mechanics while building a platform-independent game system with Matrix as the interface.

Contributions, bug reports, ideas, and feedback are welcome.

## Getting started

1. Fork or clone the repository.
2. Make sure you're working from the `development` branch.
3. Set up your local development environment.
4. Create a feature branch for your changes.

We use Python, Poetry, pytest, MongoDB, and Redis.

## Branching

We use the following branches:

- `production`: Stable releases. Do not push directly to this branch.
- `development`: Main integration branch for ongoing development.
- `feature/*`: New features and larger changes.
- `fix/*`: Bug fixes.
- `docs/*`: Documentation changes.

Please avoid committing directly to `development` when working collaboratively. Open a pull request instead.

## Pull requests

All contributions should be submitted through pull requests targeting `development`.

Before opening a PR:

- Make sure your branch is up to date with `development`.
- Test your changes where practical.
- Keep changes focused on one feature or fix.
- Include a description of what you changed and why.
- Mention any related issues.

Please don't merge your own PR without review from a maintainer.

## Code and architecture

A major goal of PokeMatrix is to separate game mechanics from platform-specific functionality.

When contributing:

- Keep reusable game logic independent of Matrix-specific code.
- Avoid introducing Discord dependencies into new code.
- Keep Matrix client and event handling inside the Matrix platform layer.
- Avoid unnecessary changes to existing database models.
- Discuss larger architectural changes before implementing them.

We want to preserve as much of the original game functionality as possible while making the underlying systems easier to maintain.

## Testing

We use pytest for automated testing.

Run the test suite with:

    poetry run pytest

Please add or update tests when changing existing functionality.

## Commit messages

Keep commit messages short and descriptive.

Examples:

- feat: add matrix room configuration
- fix: correct pokemon spawn selection
- test: add species lookup tests
- docs: update installation instructions

## Questions and suggestions

If you're unsure about an implementation, have an idea, or want to discuss a larger change, feel free to open an issue or bring it up with the maintainers.

Thanks for helping build PokeMatrix!

