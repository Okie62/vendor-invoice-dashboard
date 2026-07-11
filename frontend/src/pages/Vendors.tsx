import { useQuery } from '@tanstack/react-query';
import { Building2 } from 'lucide-react';
import { getVendors } from '../lib/api';

export default function Vendors() {
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
          <div key={v.id} className="p-4 rounded-card" style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}>
            <h3 className="text-sm font-semibold" style={{ color: 'var(--th-text-primary)' }}>{v.name}</h3>
            {v.email_domain && (
              <p className="text-xs mt-1" style={{ color: 'var(--th-text-tertiary)' }}>{v.email_domain}</p>
            )}
          </div>
        ))}
        {vendors.length === 0 && (
          <p className="text-sm col-span-full text-center py-8" style={{ color: 'var(--th-text-tertiary)' }}>No vendors found.</p>
        )}
      </div>
    </div>
  );
}