import { Component, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';

@Component({
  selector: 'app-roles-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './roles-page.component.html',
  styleUrl: './roles-page.component.scss',
})
export class RolesPageComponent implements OnInit {
  roles = signal<Role[]>([]);
  isLoading = signal(true);
  selectedRole = signal<Role | null>(null);

  ngOnInit(): void {
    this.loadRoles();
  }

  private async loadRoles(): Promise<void> {
    this.isLoading.set(true);

    // Mock data - will be replaced with real API call
    setTimeout(() => {
      this.roles.set([
        {
          id: 'admin',
          name: 'Administrator',
          description: 'Full system access with all permissions',
          permissions: [
            'users.read', 'users.create', 'users.update', 'users.delete',
            'roles.read', 'roles.create', 'roles.update', 'roles.delete',
            'catalog.read', 'catalog.create', 'catalog.update', 'catalog.delete',
            'detection.run', 'detection.configure',
            'training.run', 'training.configure',
            'settings.read', 'settings.update',
          ],
          isSystem: true,
          userCount: 1,
        },
        {
          id: 'operator',
          name: 'Operator',
          description: 'Can run detection and training, manage catalog',
          permissions: [
            'catalog.read', 'catalog.create', 'catalog.update',
            'detection.run',
            'training.run',
          ],
          isSystem: true,
          userCount: 3,
        },
        {
          id: 'viewer',
          name: 'Viewer',
          description: 'Read-only access to view detection results',
          permissions: [
            'catalog.read',
            'detection.run',
          ],
          isSystem: true,
          userCount: 5,
        },
      ]);
      this.isLoading.set(false);
    }, 500);
  }

  selectRole(role: Role): void {
    this.selectedRole.set(role);
  }

  closeDetails(): void {
    this.selectedRole.set(null);
  }

  getPermissionCategory(permission: string): string {
    return permission.split('.')[0];
  }

  getPermissionAction(permission: string): string {
    return permission.split('.')[1];
  }

  groupPermissions(permissions: string[]): Map<string, string[]> {
    const groups = new Map<string, string[]>();

    permissions.forEach(permission => {
      const category = this.getPermissionCategory(permission);
      if (!groups.has(category)) {
        groups.set(category, []);
      }
      groups.get(category)!.push(permission);
    });

    return groups;
  }
}

interface Role {
  id: string;
  name: string;
  description: string;
  permissions: string[];
  isSystem: boolean;
  userCount: number;
}
