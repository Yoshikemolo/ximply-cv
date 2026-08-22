/**
 * Application routing configuration.
 *
 * Defines all application routes with lazy loading for features.
 */

import { Routes } from '@angular/router';
import { authGuard } from '@core/guards/auth.guard';
import { roleGuard } from '@core/guards/role.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: 'view',
    pathMatch: 'full',
  },
  {
    path: 'auth',
    loadChildren: () =>
      import('@features/auth/auth.routes').then((m) => m.AUTH_ROUTES),
  },
  {
    path: 'view',
    loadComponent: () =>
      import('@features/view/view-page.component').then(
        (m) => m.ViewPageComponent
      ),
    canActivate: [authGuard],
    data: { requiredPermissions: ['detection:view'] },
  },
  {
    path: 'learn',
    loadComponent: () =>
      import('@features/learn/learn-page.component').then(
        (m) => m.LearnPageComponent
      ),
    canActivate: [authGuard],
    data: { requiredPermissions: ['objects:write'] },
  },
  {
    path: 'catalog',
    loadComponent: () =>
      import('@features/catalog/catalog-page.component').then(
        (m) => m.CatalogPageComponent
      ),
    canActivate: [authGuard],
    data: { requiredPermissions: ['objects:read'] },
  },
  {
    path: 'integrations',
    loadComponent: () =>
      import('@features/integrations/integrations-page.component').then(
        (m) => m.IntegrationsPageComponent
      ),
    canActivate: [authGuard],
    data: { requiredPermissions: ['events:manage'] },
  },
  {
    path: 'admin',
    loadChildren: () =>
      import('@features/admin/admin.routes').then((m) => m.ADMIN_ROUTES),
    canActivate: [authGuard, roleGuard],
    data: { requiredRoles: ['admin'] },
  },
  {
    path: '**',
    redirectTo: 'view',
  },
];
