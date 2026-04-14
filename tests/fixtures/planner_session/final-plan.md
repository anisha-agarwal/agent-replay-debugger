# Final Plan: API Router Refactor

## Decision
Adopt Design A (Express-style router) with modifications from critic feedback.

## Implementation Steps
1. Create `routes.ts` with centralized route definitions
2. Migrate existing handlers to new pattern
3. Add middleware composition layer
4. Update tests to reflect new structure
