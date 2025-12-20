/**
 * Error handling HTTP interceptor.
 *
 * Handles common HTTP errors and provides appropriate responses.
 */

import {
  HttpInterceptorFn,
  HttpRequest,
  HttpHandlerFn,
  HttpErrorResponse,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '@core/services/auth.service';

export const errorInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn
) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      let errorMessage = 'An unexpected error occurred';

      if (error.error instanceof ErrorEvent) {
        // Client-side error
        errorMessage = error.error.message;
      } else {
        // Server-side error
        // Check if this is an auth endpoint (login/register should not trigger logout)
        const isAuthEndpoint = req.url.includes('/auth/login') || req.url.includes('/auth/register');

        switch (error.status) {
          case 0:
            errorMessage = 'Unable to connect to server';
            break;
          case 400:
            errorMessage = error.error?.detail || 'Bad request';
            break;
          case 401:
            if (isAuthEndpoint) {
              // For auth endpoints, pass through the backend error
              errorMessage = error.error?.detail || 'Invalid credentials';
            } else {
              // For other endpoints, logout and redirect
              authService.logout();
              errorMessage = 'Session expired. Please login again.';
            }
            break;
          case 403:
            errorMessage = 'You do not have permission to perform this action';
            break;
          case 404:
            errorMessage = error.error?.detail || 'Resource not found';
            break;
          case 409:
            errorMessage = error.error?.detail || 'Resource already exists';
            break;
          case 422:
            errorMessage = error.error?.detail || 'Validation error';
            break;
          case 500:
            errorMessage = 'Internal server error';
            break;
          case 502:
          case 503:
          case 504:
            errorMessage = 'Service temporarily unavailable';
            break;
          default:
            errorMessage = error.error?.detail || `Error: ${error.status}`;
        }
      }

      // Log error in development
      if (!navigator.onLine) {
        errorMessage = 'No internet connection';
      }

      console.error('HTTP Error:', {
        status: error.status,
        message: errorMessage,
        url: req.url,
      });

      return throwError(() => ({
        status: error.status,
        message: errorMessage,
        originalError: error,
      }));
    })
  );
};
