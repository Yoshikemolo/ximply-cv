/**
 * Authentication HTTP interceptor.
 *
 * Adds JWT Bearer token to outgoing API requests.
 */

import { HttpInterceptorFn, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from '@core/services/auth.service';
import { environment } from '@env';

export const authInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn
) => {
  const authService = inject(AuthService);

  // Only add token to API requests
  if (!req.url.startsWith(environment.apiUrl)) {
    return next(req);
  }

  // Skip auth endpoints
  if (req.url.includes('/auth/login') || req.url.includes('/auth/register')) {
    return next(req);
  }

  const token = authService.getAccessToken();
  if (token) {
    const authReq = req.clone({
      setHeaders: {
        Authorization: `Bearer ${token}`,
      },
    });
    return next(authReq);
  }

  return next(req);
};
