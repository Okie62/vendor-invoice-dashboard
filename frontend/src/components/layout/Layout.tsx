import { useState } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import { Menu } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import Sidebar from './Sidebar';

export default function Layout() {
  const { isAuthenticated, isLoading } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center" style={{ backgroundColor: 'var(--th-bg)' }}>
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-t-transparent" style={{ borderColor: 'var(--color-brand)', borderTopColor: 'transparent' }} />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="flex h-screen" style={{ backgroundColor: 'var(--th-bg)' }}>
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-40 bg-black/50 md:hidden" onClick={() => setMobileMenuOpen(false)} />
      )}
      <Sidebar mobileOpen={mobileMenuOpen} onMobileClose={() => setMobileMenuOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden" style={{ backgroundColor: 'var(--th-surface-1)' }}>
        {/* Mobile top bar */}
        <header className="flex h-14 flex-shrink-0 items-center justify-between px-4 md:hidden" style={{ borderBottom: '1px solid var(--th-border)', backgroundColor: 'var(--th-surface-0)' }}>
          <button onClick={() => setMobileMenuOpen(true)} className="flex h-9 w-9 items-center justify-center rounded-md" style={{ color: 'var(--th-text-secondary)' }}>
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-base font-semibold" style={{ color: 'var(--th-text-primary)' }}>Vendor Dashboard</span>
          <div className="w-9" />
        </header>
        <main className="app-canvas flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}