import { Routes } from '@angular/router';

export const ADMIN_ROUTES: Routes = [
  {
    path: '',
    redirectTo: 'users',
    pathMatch: 'full',
  },
  {
    path: 'users',
    loadComponent: () =>
      import('./pages/users/users-page.component').then(m => m.UsersPageComponent),
  },
  {
    path: 'roles',
    loadComponent: () =>
      import('./pages/roles/roles-page.component').then(m => m.RolesPageComponent),
  },
  {
    path: 'settings',
    loadComponent: () =>
      import('./pages/settings/settings-page.component').then(m => m.SettingsPageComponent),
  },
];
