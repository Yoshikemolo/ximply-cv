import { Routes } from '@angular/router';

export const AUTH_ROUTES: Routes = [
  {
    path: 'login',
    loadComponent: () =>
      import('./pages/login/login-page.component').then(m => m.LoginPageComponent),
  },
  {
    path: '',
    redirectTo: 'login',
    pathMatch: 'full',
  },
];
