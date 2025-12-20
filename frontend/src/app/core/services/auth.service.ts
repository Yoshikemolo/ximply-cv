/**
 * Authentication service.
 *
 * Manages user authentication, token storage, and session state.
 */

import { Injectable, inject, signal, computed } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, BehaviorSubject, tap, catchError, of, throwError } from 'rxjs';
import { HttpClient } from '@angular/common/http';
import { environment } from '@env';

export interface User {
  id: string;
  email: string;
  fullName: string;
  roles: string[];
  permissions: string[];
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  isSystem: boolean;
}

export interface BackendUser {
  id: string;
  email: string;
  fullName: string;
  status: string;
  isSuperuser: boolean;
  roles: Role[];
}

export interface LoginResponse {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  expiresIn: number;
  user: BackendUser;
}

export interface TokenPayload {
  sub: string;
  email: string;
  roles: string[];
  permissions: string[];
  exp: number;
  iat: number;
}

const ACCESS_TOKEN_KEY = 'ximply-vision-access-token';
const REFRESH_TOKEN_KEY = 'ximply-vision-refresh-token';
const USER_KEY = 'ximply-vision-user';

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private readonly apiUrl = `${environment.apiUrl}/${environment.apiVersion}/auth`;

  /** Current authenticated user. */
  private readonly _user = signal<User | null>(null);

  /** Current user (readonly). */
  readonly user = this._user.asReadonly();

  /** Whether user is authenticated. */
  readonly isAuthenticated = computed(() => this._user() !== null);

  /** User's roles. */
  readonly roles = computed(() => this._user()?.roles ?? []);

  /** User's permissions. */
  readonly permissions = computed(() => this._user()?.permissions ?? []);

  constructor() {
    this.loadStoredUser();
  }

  /**
   * Login with email and password.
   *
   * @param credentials - Login credentials.
   * @returns Observable of login response.
   */
  login(credentials: LoginRequest): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${this.apiUrl}/login`, credentials)
      .pipe(
        tap((response) => {
          this.storeTokens(response.accessToken, response.refreshToken);

          // Decode token to get roles and permissions
          const tokenData = this.decodeToken(response.accessToken);

          // Transform backend user to frontend user
          const user: User = {
            id: response.user.id,
            email: response.user.email,
            fullName: response.user.fullName,
            roles: tokenData?.roles ?? response.user.roles.map(r => r.name),
            permissions: tokenData?.permissions ?? [],
          };

          this.storeUser(user);
          this._user.set(user);
        })
      );
  }

  /**
   * Register a new user.
   *
   * @param data - Registration data.
   * @returns Observable of user.
   */
  register(data: {
    email: string;
    password: string;
    fullName: string;
  }): Observable<User> {
    return this.http.post<User>(`${this.apiUrl}/register`, data);
  }

  /**
   * Logout current user.
   */
  logout(): void {
    this.clearStorage();
    this._user.set(null);
    this.router.navigate(['/auth/login']);
  }

  /**
   * Refresh access token.
   *
   * @returns Observable of new access token.
   */
  refreshToken(): Observable<{ accessToken: string }> {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) {
      return throwError(() => new Error('No refresh token'));
    }

    return this.http
      .post<{ accessToken: string; tokenType: string; expiresIn: number }>(
        `${this.apiUrl}/refresh`,
        { refreshToken }
      )
      .pipe(
        tap((response) => {
          localStorage.setItem(ACCESS_TOKEN_KEY, response.accessToken);
        }),
        catchError((error) => {
          this.logout();
          return throwError(() => error);
        })
      );
  }

  /**
   * Get stored access token.
   */
  getAccessToken(): string | null {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  }

  /**
   * Get stored refresh token.
   */
  getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }

  /**
   * Check if user has a specific permission.
   *
   * @param permission - Permission to check.
   * @returns True if user has permission.
   */
  hasPermission(permission: string): boolean {
    return this.permissions().includes(permission);
  }

  /**
   * Check if user has any of the specified permissions.
   *
   * @param permissions - Permissions to check.
   * @returns True if user has any permission.
   */
  hasAnyPermission(permissions: string[]): boolean {
    return permissions.some((p) => this.permissions().includes(p));
  }

  /**
   * Check if user has a specific role.
   *
   * @param role - Role to check.
   * @returns True if user has role.
   */
  hasRole(role: string): boolean {
    return this.roles().includes(role);
  }

  /**
   * Check if user has any of the specified roles.
   *
   * @param roles - Roles to check.
   * @returns True if user has any role.
   */
  hasAnyRole(roles: string[]): boolean {
    return roles.some((r) => this.roles().includes(r));
  }

  /**
   * Load user from storage on app init.
   */
  private loadStoredUser(): void {
    const stored = localStorage.getItem(USER_KEY);
    if (stored) {
      try {
        const user = JSON.parse(stored) as User;
        // Verify token is still valid
        const token = this.getAccessToken();
        if (token && !this.isTokenExpired(token)) {
          this._user.set(user);
        } else {
          this.clearStorage();
        }
      } catch {
        this.clearStorage();
      }
    }
  }

  /**
   * Check if JWT token is expired.
   *
   * @param token - JWT token.
   * @returns True if expired.
   */
  private isTokenExpired(token: string): boolean {
    try {
      const payload = this.decodeToken(token);
      if (!payload) return true;
      // Add 60 second buffer
      return payload.exp * 1000 < Date.now() - 60000;
    } catch {
      return true;
    }
  }

  /**
   * Decode JWT token payload.
   *
   * @param token - JWT token.
   * @returns Token payload or null.
   */
  private decodeToken(token: string): TokenPayload | null {
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return null;
      const payload = JSON.parse(atob(parts[1]));
      return payload as TokenPayload;
    } catch {
      return null;
    }
  }

  /**
   * Store tokens in localStorage.
   */
  private storeTokens(accessToken: string, refreshToken: string): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  }

  /**
   * Store user in localStorage.
   */
  private storeUser(user: User): void {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  /**
   * Clear all stored auth data.
   */
  private clearStorage(): void {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }
}
