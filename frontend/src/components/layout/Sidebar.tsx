import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FileText,
  Users,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
  X,
  Building2,
  ShieldCheck,
  ClipboardList,
  UserCheck,
} from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useTheme } from '../../hooks/useTheme';

const mainNav = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Invoices', href: '/invoices', icon: FileText },
  { name: 'Vendors', href: '/vendors', icon: Building2 },
];

const adminNav = [
  { name: 'Users', href: '/admin/users', icon: ShieldCheck },
  { name: 'Format Review', href: '/admin/reviews', icon: ClipboardList },
];

interface SidebarProps {
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export default function Sidebar({ mobileOpen = false, onMobileClose }: SidebarProps) {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);

  const navItems = [
    ...mainNav,
    ...(user?.is_admin ? adminNav : []),
  ];

  return (
    <div
      className={`flex flex-col fixed inset-y-0 left-0 z-50 md:static md:inset-auto md:z-auto md:h-full transition-transform duration-200 ${collapsed ? 'w-60 md:w-16' : 'w-60'} ${mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}`}
      style={{ backgroundColor: 'var(--th-surface-0)', borderRight: '1px solid var(--th-border)' }}
    >
      {/* Logo */}
      <div className="flex h-14 items-center relative" style={{ borderBottom: '1px solid var(--th-border)' }}>
        <div className={`flex-1 flex items-center ${collapsed ? 'justify-center px-4' : 'px-4'}`}>
          {collapsed ? (
            <span className="text-base font-semibold" style={{ color: 'var(--th-accent)' }}>VID</span>
          ) : (
            <h1 className="text-base font-semibold tracking-tight" style={{ color: 'var(--th-accent)' }}>
              Vendor Dashboard
            </h1>
          )}
        </div>
        <button onClick={onMobileClose} className="mr-3 flex h-8 w-8 items-center justify-center rounded-md md:hidden" style={{ color: 'var(--th-text-tertiary)' }}>
          <X className="h-4 w-4" />
        </button>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="absolute -right-3 top-1/2 -translate-y-1/2 z-10 hidden md:flex h-5 w-5 items-center justify-center rounded-full transition-colors"
          style={{ backgroundColor: 'var(--th-surface-2)', border: '1px solid var(--th-border-strong)', color: 'var(--th-text-tertiary)' }}
        >
          {collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronLeft className="h-3 w-3" />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-2 py-3 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.name}
            to={item.href}
            title={collapsed ? item.name : undefined}
            onClick={onMobileClose}
            className={({ isActive }) =>
              `group flex items-center rounded-comfortable text-caption-lg font-medium transition-colors ${
                collapsed ? 'justify-center px-2 py-3 md:py-2' : 'px-2.5 py-3 md:py-1.5'
              }`
            }
            style={({ isActive }) => ({
              backgroundColor: isActive ? 'var(--th-active)' : 'transparent',
              color: isActive ? 'var(--th-text-primary)' : 'var(--th-text-tertiary)',
            })}
          >
            <item.icon className={`h-4 w-4 flex-shrink-0 ${collapsed ? '' : 'mr-2.5'}`} strokeWidth={1.75} />
            {!collapsed && <span className="flex-1">{item.name}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Theme toggle + User */}
      <div style={{ borderTop: '1px solid var(--th-border)' }}>
        <div className={`px-3 pt-3 ${collapsed ? 'flex justify-center' : ''}`}>
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            className={`flex items-center rounded-comfortable transition-colors ${collapsed ? 'p-2 justify-center' : 'w-full px-2.5 py-1.5 gap-2.5'}`}
            style={{ color: 'var(--th-text-tertiary)' }}
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" strokeWidth={1.75} /> : <Moon className="h-4 w-4" strokeWidth={1.75} />}
            {!collapsed && <span className="text-caption-lg font-medium">{theme === 'dark' ? 'Light Mode' : 'Dark Mode'}</span>}
          </button>
        </div>
        <div className="p-3">
          {collapsed ? (
            <button onClick={logout} title="Sign out" className="flex w-full items-center justify-center rounded-comfortable p-2 transition-colors" style={{ color: 'var(--th-text-quaternary)' }}>
              <LogOut className="h-4 w-4" />
            </button>
          ) : (
            <div className="flex items-center">
              <div className="flex-1 min-w-0">
                <p className="text-caption font-medium truncate" style={{ color: 'var(--th-accent-muted)' }}>
                  {user?.full_name || user?.email}
                </p>
                <p className="text-label truncate" style={{ color: 'var(--th-text-quaternary)' }}>
                  {user?.email}
                </p>
              </div>
              <button onClick={logout} className="ml-2 flex-shrink-0 rounded-comfortable p-1.5 transition-colors" style={{ color: 'var(--th-text-quaternary)' }} title="Sign out">
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}