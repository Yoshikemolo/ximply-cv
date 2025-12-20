import { Component, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { AuthService } from '@core/services/auth.service';
import { ThemeService } from '@core/services/theme.service';

@Component({
  selector: 'app-login-page',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, TranslateModule],
  templateUrl: './login-page.component.html',
  styleUrl: './login-page.component.scss',
})
export class LoginPageComponent {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly authService = inject(AuthService);
  private readonly themeService = inject(ThemeService);

  /** Logo path based on current theme. */
  readonly logoPath = computed(() =>
    this.themeService.isDarkMode()
      ? 'assets/images/dark-color-logo-with-claim.svg'
      : 'assets/images/light-color-logo-with-claim.svg'
  );

  loginForm: FormGroup;
  isLoading = signal(false);
  errorMessage = signal<string | null>(null);
  showPassword = signal(false);

  constructor() {
    this.loginForm = this.fb.group({
      email: ['', [Validators.required, Validators.email]],
      password: ['', [Validators.required, Validators.minLength(8)]],
      rememberMe: [false],
    });
  }

  togglePasswordVisibility(): void {
    this.showPassword.update(v => !v);
  }

  async onSubmit(): Promise<void> {
    if (this.loginForm.invalid) {
      this.loginForm.markAllAsTouched();
      return;
    }

    this.isLoading.set(true);
    this.errorMessage.set(null);

    try {
      const { email, password } = this.loginForm.value;
      this.authService.login({ email, password }).subscribe({
        next: () => {
          this.router.navigate(['/view']);
        },
        error: (error: any) => {
          this.errorMessage.set(error.message || 'auth.errors.loginFailed');
          this.isLoading.set(false);
        },
        complete: () => {
          this.isLoading.set(false);
        }
      });
    } catch (error: any) {
      this.errorMessage.set(error.message || 'auth.errors.loginFailed');
      this.isLoading.set(false);
    }
  }

  get emailControl() {
    return this.loginForm.get('email');
  }

  get passwordControl() {
    return this.loginForm.get('password');
  }
}
