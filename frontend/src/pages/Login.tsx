import { useState, useEffect, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { checkSetup, login as apiLogin, register as apiRegister } from '../lib/api';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [isRegisterMode, setIsRegisterMode] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [hideToggle, setHideToggle] = useState(false);

  useEffect(() => {
    checkSetup().then((data) => {
      if (!data.has_users) {
        setIsRegisterMode(true);
        setHideToggle(true);
      }
    }).catch(() => {});
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegisterMode) {
        const resp = await apiRegister(email, password, fullName);
        localStorage.setItem('access_token', resp.access_token);
        localStorage.setItem('refresh_token', resp.refresh_token);
      } else {
        await login(email, password);
      }
      navigate('/', { replace: true });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Something went wrong';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-6" style={{ backgroundColor: 'var(--th-bg)' }}>
      <div className="w-full max-w-md" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)', borderRadius: 16, padding: 40 }}>
        <div className="text-center mb-8">
          <span className="inline-block bg-gradient-to-r from-[#3b82f6] to-[#8b5cf6] px-3.5 py-1.5 rounded-md text-sm font-semibold text-white mb-4">OTS</span>
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--th-text-primary)' }}>{isRegisterMode ? 'Create Account' : 'Sign In'}</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--th-text-tertiary)' }}>Vendor Invoice Dashboard · Oklahoma Technology Solutions</p>
        </div>

        <form onSubmit={handleSubmit}>
          {isRegisterMode && (
            <div className="mb-4">
              <label className="block text-xs uppercase tracking-wider mb-1.5" style={{ color: 'var(--th-text-tertiary)' }}>Full Name</label>
              <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jay Wade" className="w-full px-3.5 py-3 rounded-lg text-sm outline-none" style={{ backgroundColor: 'var(--th-input-bg)', border: '1px solid var(--th-input-border)', color: 'var(--th-text-primary)' }} />
            </div>
          )}
          <div className="mb-4">
            <label className="block text-xs uppercase tracking-wider mb-1.5" style={{ color: 'var(--th-text-tertiary)' }}>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@oktechsol.com" required className="w-full px-3.5 py-3 rounded-lg text-sm outline-none" style={{ backgroundColor: 'var(--th-input-bg)', border: '1px solid var(--th-input-border)', color: 'var(--th-text-primary)' }} />
          </div>
          <div className="mb-6">
            <label className="block text-xs uppercase tracking-wider mb-1.5" style={{ color: 'var(--th-text-tertiary)' }}>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required className="w-full px-3.5 py-3 rounded-lg text-sm outline-none" style={{ backgroundColor: 'var(--th-input-bg)', border: '1px solid var(--th-input-border)', color: 'var(--th-text-primary)' }} />
          </div>
          <button type="submit" disabled={loading} className="w-full py-3 rounded-lg text-sm font-semibold text-white transition-opacity disabled:opacity-50" style={{ backgroundColor: 'var(--color-brand)' }}>
            {loading ? 'Please wait...' : isRegisterMode ? 'Register' : 'Sign In'}
          </button>
        </form>

        {error && <p className="text-sm text-center mt-4" style={{ color: '#ef4444' }}>{error}</p>}

        {!hideToggle && (
          <p className="text-sm text-center mt-5" style={{ color: 'var(--th-text-tertiary)' }}>
            {isRegisterMode ? "Already have an account? " : "Don't have an account? "}
            <button onClick={() => { setIsRegisterMode(!isRegisterMode); setError(''); }} className="font-medium" style={{ color: 'var(--th-accent)' }}>
              {isRegisterMode ? 'Sign In' : 'Register'}
            </button>
          </p>
        )}
      </div>
    </div>
  );
}