import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Building2, ArrowUpRight, FileText } from 'lucide-react';
import { getVendors } from '../lib/api';

export default function Vendors() {
  const navigate = useNavigate();
  const { data: vendors = [] } = useQuery({ queryKey: ['vendors'], queryFn: getVendors });

  return (
    <div className="min-h-full p-3 sm:p-6" style={{ backgroundColor: 'var(--th-surface-1)' }}>
      <div className="mb-4 flex items-center gap-2">
        <Building2 className="h-5 w-5" style={{ color: 'var(--color-brand)' }} />
        <h1 className="text-xl font-semibold" style={{ color: 'var(--th-text-primary)' }}>Vendors</h1>
        <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)' }}>{vendors.length}</span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {vendors.map((v) => (
          <div
            key={v.id}
            onClick={() => navigate(`/vendors/${v.id}`)}
            className="p-4 rounded-card cursor-pointer transition-all hover:translate-y-[-1px]"
            style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg shrink-0" style={{ backgroundColor: 'rgba(57,216,189,0.12)', color: 'var(--th-accent)' }}>
                  <Building2 className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold truncate" style={{ color: 'var(--th-text-primary)' }}>{v.name}</h3>
                  {v.email_domain && (
                    <p className="text-xs mt-0.5 truncate" style={{ color: 'var(--th-text-tertiary)' }}>{v.email_domain}</p>
                  )}
                </div>
              </div>
              <ArrowUpRight className="h-4 w-4 shrink-0" style={{ color: 'var(--th-accent)' }} />
            </div>
          </div>
        ))}
        {vendors.length === 0 && (
          <p className="text-sm col-span-full text-center py-8" style={{ color: 'var(--th-text-tertiary)' }}>No vendors found.</p>
        )}
      </div>
    </div>
  );
}