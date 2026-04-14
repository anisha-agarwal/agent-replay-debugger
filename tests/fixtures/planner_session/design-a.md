# Design A: Express-style Router

## Approach
Use a flat router with middleware chain pattern.

## Implementation
1. Define routes in a central `routes.ts` file
2. Each route maps to a handler function
3. Middleware applied via composition
