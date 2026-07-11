import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText } from 'lucide-react';
import { getInvoices, type Invoice } from '../lib/api';

function fmtMoney(n: number) {
  const sign = n < 0 ? '-' : '';
  return sign + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function Invoices() {
  const [search, setSearch] = useState('');
  const { data: invoices = [] } = useQuery({
    queryKey: ['invoices', { search: search || undefined }],
    queryFn: () => getInvoices({ search: search || undefined }),
  });

  return (
    <div className="min-h-full p-3 sm:p-6" style={{ backgroundColor: 'var(--th-surface-1)' }}>
      <div className="mb-4 flex items-center gap-2">
        <FileText className="h-5 w-5" style={{ color: 'var(--color-brand)' }} />
        <h1 className="text-xl font-semibold" style={{ color: 'var(--th-text-primary)' }}>Invoices</h1>
        <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: 'var(--th-surface-2)', color: 'var(--th-text-tertiary)' }}>{invoices.length}</span>
      </div>

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by invoice ID or billing period..."
        className="w-full max-w-md px-3 py-2 text-sm rounded-lg mb-4"
        style={{ backgroundColor: 'var(--th-surface-0)', border: '1px solid var(--th-border)' }}
      />

      <div className="overflow-x-auto rounded-card" style={{ border: '1px solid var(--th-border)' }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ backgroundColor: 'var(--th-surface-0)' }}>
              {['Invoice ID', 'Vendor', 'Billing Period', 'Previous Balance', 'New Charges', 'Outstanding', 'Credit Memo'].map((h) => (
                <th key={h} className="px-3 py-2 text-left text-xs font-semibold uppercase" style={{ color: 'var(--th-text-tertiary)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id} style={{ borderTop: '1px solid var(--th-border)' }}>
                <td className="px-3 py-2 font-mono text-xs" style={{ color: 'var(--th-accent)' }}>#{inv.id}</td>
                <td className="px-3 py-2">{inv.vendor}</td>
                <td className="px-3 py-2" style={{ color: 'var(--th-text-secondary)' }}>{inv.billing_period}</td>
                <td className="px-3 py-2 text-right">{fmtMoney(inv.summary.previous_balance)}</td>
                <td className="px-3 py-2 text-right font-semibold">{fmtMoney(inv.summary.new_charges)}</td>
                <td className="px-3 py-2 text-right">{fmtMoney(inv.summary.outstanding_balance)}</td>
                <td className="px-3 py-2 text-center">
                  {inv.is_credit_memo && <span className="px-2 py-0.5 rounded-full text-xs font-semibold" style={{ backgroundColor: 'rgba(34,197,94,0.15)', color: '#4ade80' }}>Credit</span>}
                </td>
              </tr>
            ))}
            {invoices.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-sm" style={{ color: 'var(--th-text-tertiary)' }}>No invoices found.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}