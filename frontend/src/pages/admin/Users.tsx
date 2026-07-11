import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, Search, UserPlus } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { getAdminUsers, createAdminUser, toggleAdminRole, deactivateUser } from '../../lib/api';
import type { AdminUser } from '../../lib/api';

export default function Users() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newName, setNewName] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const { data: users = [], isLoading } = useQuery({
    queryKey: ['admin-users'],
    queryFn: getAdminUsers,
    enabled: !!user?.is_admin,
  });

  const createMutation = useMutation({
    mutationFn: () => createAdminUser({ email: newEmail, password: newPassword, full_name: newName }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] });
      setShowAdd(false);
      setNewEmail('');
      setNewName('');
      setNewPassword('');
      setError(null);
    },
    onError: (e: Error) => setError(e.message || 'Create failed'),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_admin }: { id: number; is_admin: boolean }) => toggleAdminRole(id, is_admin),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ['admin-users'] });
    },
    onError: (e: Error) => setError(e.message || 'Update failed'),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: number) => deactivateUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] });
    },
    onError: (e: Error) => setError(e.message || 'Deactivate failed'),
  });

  const filtered = users.filter((u) =>
    !search || u.full_name.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase())
  );

  if (!user?.is_admin) {
    return (
      <div className="p-8">
        <p className="text-sm" style={{ color: 'var(--th-text-secondary)' }}>You don't have access to user management.</p>
      </div>
    );
  }

  return (
    <div className="min-h-full p-3 sm:p-6" style={{ backgroundColor: 'var(--th-surface-1)' }}>
      <div className="mx-auto max-w-3xl">
        <div className="mb-2 flex items-center gap-2">
          <ShieldCheck className="h-6 w-6" style={{ color: 'var(--color-brand)' }} />
          <h1 className="text-xl font-semibold" style={{ color: 'var(--th-text-primary)' }}>Users</h1>
        </div>
        <p className="mb-5 text-sm" style={{ color: 'var(--th-text-tertiary)' }}>
          Manage dashboard users. Only admins can add users, toggle admin roles, or deactivate accounts.
        </p>

        <div className="flex items-center gap-3 mb-4">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4" style={{ color: 'var(--th-text-quaternary)' }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or email…"
              className="w-full rounded-comfortable pl-9 pr-3 py-2 text-sm focus:outline-none"
              style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border-strong)', color: 'var(--th-text-primary)' }}
            />
          </div>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-comfortable text-white"
            style={{ backgroundColor: 'var(--color-brand)' }}
          >
            <UserPlus className="h-4 w-4" />
            Add User
          </button>
        </div>

        {error && <p className="mb-3 text-sm" style={{ color: '#ef4444' }}>{error}</p>}

        {/* Add User Form */}
        {showAdd && (
          <div className="mb-4 p-4 rounded-card" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
            <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--th-text-primary)' }}>New User</h3>
            <div className="grid grid-cols-3 gap-3 mb-3">
              <div>
                <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Full Name</label>
                <input value={newName} onChange={(e) => setNewName(e.target.value)} className="w-full px-2.5 py-2 text-sm rounded" />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Email</label>
                <input value={newEmail} onChange={(e) => setNewEmail(e.target.value)} className="w-full px-2.5 py-2 text-sm rounded" />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider mb-1" style={{ color: 'var(--th-text-tertiary)' }}>Password</label>
                <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="w-full px-2.5 py-2 text-sm rounded" />
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => createMutation.mutate()} disabled={createMutation.isPending} className="px-4 py-1.5 text-sm font-medium rounded-comfortable text-white disabled:opacity-50" style={{ backgroundColor: 'var(--color-brand)' }}>
                {createMutation.isPending ? 'Creating...' : 'Create'}
              </button>
              <button onClick={() => setShowAdd(false)} className="px-4 py-1.5 text-sm rounded-comfortable" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)' }}>Cancel</button>
            </div>
          </div>
        )}

        {isLoading && <p className="text-sm" style={{ color: 'var(--th-text-tertiary)' }}>Loading…</p>}

        <div className="overflow-hidden rounded-card" style={{ border: '1px solid var(--th-border)' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: 'var(--th-surface-0)' }}>
                <th className="px-4 py-2.5 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>User</th>
                <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Admin</th>
                <th className="px-4 py-2.5 text-center text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Active</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((u) => (
                <tr key={u.id} style={{ borderTop: '1px solid var(--th-border)' }}>
                  <td className="px-4 py-3">
                    <div className="font-medium" style={{ color: 'var(--th-text-primary)' }}>{u.full_name}</div>
                    <div className="text-xs" style={{ color: 'var(--th-text-tertiary)' }}>{u.email}</div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <button
                      onClick={() => toggleMutation.mutate({ id: u.id, is_admin: !u.is_admin })}
                      disabled={toggleMutation.isPending}
                      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50"
                      style={u.is_admin ? { backgroundColor: 'var(--color-brand)', color: '#fff' } : { backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-border-strong)' }}
                    >
                      {u.is_admin ? 'Yes' : 'No'}
                    </button>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${u.is_active ? '' : 'opacity-50'}`}
                      style={u.is_active ? { backgroundColor: 'rgba(34,197,94,0.15)', color: '#4ade80' } : { backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)', border: '1px solid var(--th-border-strong)' }}
                    >
                      {u.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {u.is_active ? (
                      <button
                        onClick={() => { if (confirm(`Deactivate ${u.full_name}?`)) deactivateMutation.mutate(u.id); }}
                        className="text-xs px-2 py-1 rounded font-medium"
                        style={{ color: 'var(--th-danger)' }}
                      >
                        Deactivate
                      </button>
                    ) : (
                      <span className="text-xs" style={{ color: 'var(--th-text-tertiary)' }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No users found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}