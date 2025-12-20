/**
 * Authentication guard.
 *
 * Protects routes that require authentication.
 */

import { inject } from '@angular/core';
import { CanActivateFn, Router, ActivatedRouteSnapshot } from '@angular/router';
import { AuthService } from '@core/services/auth.service';

export const authGuard: CanActivateFn = (route: ActivatedRouteSnapshot) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.isAuthenticated()) {
    // Store intended destination for redirect after login
    const returnUrl = route.url.map((segment) => segment.path).join('/');
    router.navigate(['/auth/login'], {
      queryParams: { returnUrl: returnUrl || '/' },
    });
    return false;
  }

  // Check required permissions if specified
  const requiredPermissions = route.data['requiredPermissions'] as
    | string[]
    | undefined;
  if (requiredPermissions && requiredPermissions.length > 0) {
    // Skip permission check if user has no permissions (new user)
    const userPermissions = authService.permissions();
    if (userPermissions.length > 0) {
      const hasPermission = authService.hasAnyPermission(requiredPermissions);
      if (!hasPermission) {
        router.navigate(['/auth/login']);
        return false;
      }
    }
    // Allow access if user has no permissions yet (will be assigned by admin)
  }

  return true;
};
