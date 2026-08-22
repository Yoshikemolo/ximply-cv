# Contributing to XIMPLY Vision

Thanks for your interest in the project. This document describes how to set up the
project and the conventions every contribution must follow.

## Getting started

```bash
git clone https://github.com/Yoshikemolo/ximply-cv.git
cd ximply-cv
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

The development override mounts `backend/app` into the container with hot reload, so
backend changes apply without a rebuild. Frontend changes require rebuilding the
frontend image, or running `npm start` locally against the containerised backend.

## Workflow

1. Branch off `main`, using a short descriptive name: `feat/catalog-bulk-import`,
   `fix/nms-overlap`.
2. Keep each commit focused on one change.
3. Run the tests before opening a pull request:
   - Backend: `cd backend && pytest`
   - Frontend: `cd frontend && npm test`
4. Open a pull request describing what changed and why.

## Commit conventions

Commits follow [Conventional Commits](https://www.conventionalcommits.org/), written in
English.

```
<type>(<optional scope>): <description>

<optional body>

<optional footer>
```

### Subject line

- `type` is one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`,
  `ci`, `chore`, `revert`.
- Optional lowercase `scope`: `backend`, `frontend`, `catalog`, `learn`, `view`,
  `admin`, `auth`, `docker`, `db`.
- The `description` starts lowercase, uses the imperative mood ("add", not "added"),
  and carries no trailing period.
- Keep the subject at 72 characters or less.

### Breaking changes

Append `!` after the type or scope, or add a `BREAKING CHANGE:` footer:

```
feat(api)!: replace presigned urls with a proxy endpoint

BREAKING CHANGE: /api/v1/objects/{id}/url no longer exists.
```

### Body

Leave a blank line after the subject. Explain what changed and why, not how. Use `- `
bullets in the imperative mood, grouped under short plain-text headings when the commit
spans several areas.

### Examples

```
feat(learn): add camera-based capture with bounding box annotation
fix(view): improve nms to better suppress overlapping detections
refactor(backend): extract feature matching into a service facade
docs: document the image proxy endpoint
chore(docker): add libzbar0 for pyzbar runtime support
```

## Style rules

These apply to commits, documentation and source alike.

- **English everywhere.** Commit messages, identifiers, comments and documentation.
- **No emojis.** Not in commit messages, documentation, code, templates or log output.
  UI icons come from the SVG icon set in `frontend/src/assets/icons`, rendered through
  the `icon-mask` classes in `frontend/src/styles/_icons.scss`.
- **No generated credit lines.** Do not add trailers, bylines or footers crediting a
  tool or generator to commits, documents or source files.

## Code conventions

### Backend (Python)

- Type hints on every function, Google-style docstrings.
- Async-first with FastAPI, Pydantic models for validation.
- Business logic behind service facades in `backend/app/services`.

### Frontend (Angular)

- Standalone components only, Signals for reactive state.
- Separate `.ts`, `.html` and `.scss` files per component.
- Path aliases: `@core/*`, `@shared/*`, `@features/*`, `@env`.
- BEM naming for CSS classes.
- Every user-facing string goes through the translation files in
  `frontend/src/assets/i18n` for both English and Spanish.

### API

- All endpoints live under `/api/v1/`. Breaking changes require a new version.
- Update `postman/ximply-vision.postman_collection.json` when endpoints change.

## Reporting issues

Open an issue with the steps to reproduce, the expected and actual behaviour, and the
relevant output of `docker compose logs backend`.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
