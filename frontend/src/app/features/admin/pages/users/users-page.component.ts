import { Component, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';

@Component({
  selector: 'app-users-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './users-page.component.html',
  styleUrl: './users-page.component.scss',
})
export class UsersPageComponent implements OnInit {
  users = signal<User[]>([]);
  isLoading = signal(true);
  searchQuery = signal('');
  showUserModal = signal(false);
  editingUser = signal<User | null>(null);
  showDeleteModal = signal(false);
  userToDelete = signal<User | null>(null);

  ngOnInit(): void {
    this.loadUsers();
  }

  private async loadUsers(): Promise<void> {
    this.isLoading.set(true);

    // Mock data - will be replaced with real API call
    setTimeout(() => {
      this.users.set([
        {
          id: '1',
          email: 'admin@ximply.io',
          name: 'Admin User',
          role: 'admin',
          isActive: true,
          createdAt: new Date('2024-01-01'),
          lastLogin: new Date('2024-03-15'),
        },
        {
          id: '2',
          email: 'operator@ximply.io',
          name: 'Operator User',
          role: 'operator',
          isActive: true,
          createdAt: new Date('2024-02-01'),
          lastLogin: new Date('2024-03-14'),
        },
        {
          id: '3',
          email: 'viewer@ximply.io',
          name: 'Viewer User',
          role: 'viewer',
          isActive: false,
          createdAt: new Date('2024-02-15'),
          lastLogin: null,
        },
      ]);
      this.isLoading.set(false);
    }, 500);
  }

  get filteredUsers(): User[] {
    const query = this.searchQuery().toLowerCase();
    if (!query) return this.users();

    return this.users().filter(user =>
      user.name.toLowerCase().includes(query) ||
      user.email.toLowerCase().includes(query)
    );
  }

  openAddUser(): void {
    this.editingUser.set(null);
    this.showUserModal.set(true);
  }

  openEditUser(user: User): void {
    this.editingUser.set({ ...user });
    this.showUserModal.set(true);
  }

  closeUserModal(): void {
    this.editingUser.set(null);
    this.showUserModal.set(false);
  }

  saveUser(userData: Partial<User>): void {
    if (this.editingUser()) {
      // Update existing user
      this.users.update(users =>
        users.map(u => u.id === this.editingUser()!.id ? { ...u, ...userData } : u)
      );
    } else {
      // Add new user
      const newUser: User = {
        id: crypto.randomUUID(),
        email: userData.email!,
        name: userData.name!,
        role: userData.role || 'viewer',
        isActive: true,
        createdAt: new Date(),
        lastLogin: null,
      };
      this.users.update(users => [...users, newUser]);
    }
    this.closeUserModal();
  }

  confirmDelete(user: User): void {
    this.userToDelete.set(user);
    this.showDeleteModal.set(true);
  }

  cancelDelete(): void {
    this.userToDelete.set(null);
    this.showDeleteModal.set(false);
  }

  deleteUser(): void {
    const user = this.userToDelete();
    if (!user) return;

    this.users.update(users => users.filter(u => u.id !== user.id));
    this.cancelDelete();
  }

  toggleUserStatus(user: User): void {
    this.users.update(users =>
      users.map(u => u.id === user.id ? { ...u, isActive: !u.isActive } : u)
    );
  }

  getRoleBadgeClass(role: string): string {
    switch (role) {
      case 'admin': return 'role-admin';
      case 'operator': return 'role-operator';
      default: return 'role-viewer';
    }
  }
}

interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  isActive: boolean;
  createdAt: Date;
  lastLogin: Date | null;
}
