# Milestone 2: Authentication

## Overview
Implement complete authentication system with user registration, login, JWT tokens, and role-based access control.

## Tasks

### 2.1 Backend Authentication
- [ ] Complete user registration endpoint
- [ ] Complete user login endpoint
- [ ] Implement password validation rules
- [ ] Implement email verification (optional)
- [ ] Complete token refresh endpoint
- [ ] Add logout endpoint (token blacklist - optional)

**Implementation Steps:**

1. Verify registration endpoint validates:
   - Email uniqueness
   - Password strength (uppercase, lowercase, digit)
   - Name length

2. Verify login endpoint:
   - Returns access and refresh tokens
   - Updates last_login timestamp
   - Collects permissions from roles

3. Add password reset flow (optional):
   - Create password reset request endpoint
   - Create password reset confirmation endpoint
   - Send email with reset link

### 2.2 RBAC Implementation
- [ ] Create permission seed data
- [ ] Create role seed data
- [ ] Implement permission checking middleware
- [ ] Implement role checking middleware
- [ ] Create role assignment endpoints

**Implementation Steps:**

1. Seed default permissions:
   ```python
   permissions = [
       ("objects:read", "Read Objects", "Objects"),
       ("objects:write", "Write Objects", "Objects"),
       ("objects:delete", "Delete Objects", "Objects"),
       ("objects:train", "Train Objects", "Objects"),
       ("detection:view", "View Detection", "Detection"),
       ("detection:configure", "Configure Detection", "Detection"),
       ("users:read", "Read Users", "Users"),
       ("users:write", "Write Users", "Users"),
       ("users:delete", "Delete Users", "Users"),
       ("roles:read", "Read Roles", "Roles"),
       ("roles:write", "Write Roles", "Roles"),
       ("admin:full", "Full Admin Access", "Admin"),
   ]
   ```

2. Seed default roles:
   - Admin: All permissions
   - Operator: objects:*, detection:*
   - Viewer: objects:read, detection:view

3. Seed admin user:
   - Email: admin@ximply-vision.local
   - Role: Admin

### 2.3 Frontend Authentication
- [ ] Create login page component
- [ ] Create register page component
- [ ] Implement auth service methods
- [ ] Implement token storage
- [ ] Implement auto-refresh token
- [ ] Create auth state management

**Implementation Steps:**

1. Create `features/auth/login/login-page.component.ts`:
   - Email and password form
   - Validation messages
   - Submit handler
   - Redirect on success

2. Create `features/auth/register/register-page.component.ts`:
   - Full name, email, password, confirm password
   - Password strength indicator
   - Terms acceptance (optional)
   - Redirect to login on success

3. Create auth routes:
   ```typescript
   export const AUTH_ROUTES: Routes = [
     { path: 'login', component: LoginPageComponent },
     { path: 'register', component: RegisterPageComponent },
     { path: '', redirectTo: 'login', pathMatch: 'full' }
   ];
   ```

4. Implement auto token refresh:
   - Check token expiry before requests
   - Refresh if close to expiry
   - Handle refresh failure (logout)

### 2.4 Protected Routes
- [ ] Implement auth guard checks
- [ ] Implement role guard checks
- [ ] Handle unauthorized redirects
- [ ] Show permission-based UI elements

**Implementation Steps:**

1. Update auth guard to check token validity
2. Update role guard to verify required roles
3. Add permission directive for UI elements:
   ```typescript
   @Directive({ selector: '[hasPermission]' })
   export class HasPermissionDirective {
     @Input() set hasPermission(permission: string) {
       // Show/hide element based on permission
     }
   }
   ```

## Verification Checklist

- [ ] User can register with valid email/password
- [ ] User receives validation errors for invalid input
- [ ] User can login with correct credentials
- [ ] Login fails with incorrect credentials
- [ ] Access token is stored and sent with requests
- [ ] Token refresh works before expiry
- [ ] Protected routes redirect unauthenticated users
- [ ] Role-restricted routes check permissions
- [ ] UI elements hide based on permissions
- [ ] Logout clears tokens and redirects

## API Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | /api/v1/auth/register | Register new user | No |
| POST | /api/v1/auth/login | Login user | No |
| POST | /api/v1/auth/refresh | Refresh token | Yes |
| GET | /api/v1/auth/me | Get current user | Yes |
| POST | /api/v1/auth/logout | Logout user | Yes |

## Next Steps
After completing authentication, proceed to Milestone 3: Object Catalog.
