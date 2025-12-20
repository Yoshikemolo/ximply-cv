/**
 * Role-based access guard.
 *
 * Protects routes that require specific roles.
 */

import { inject } from '@angular/core';
import { CanActivateFn, Router, ActivatedRouteSnapshot } from '@angular/router';
import { AuthService } from '@core/services/auth.service';

export const roleGuard: CanActivateFn = (route: ActivatedRouteSnapshot) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  const requiredRoles = route.data['requiredRoles'] as string[] | undefined;

  if (!requiredRoles || requiredRoles.length === 0) {
    return true;
  }

  const hasRole = authService.hasAnyRole(requiredRoles);

  if (!hasRole) {
    // Redirect to home or show access denied
    router.navigate(['/']);
    return false;
  }

  return true;
};
