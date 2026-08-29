import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MortgagePaymentOffer } from '../src/components/MortgagePaymentOffer';
import { api, type DebtOut, type ScheduleOut } from '../src/lib/api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const NOTE = {
  id: 'n1',
  lender: 'First Federal',
  paid_off_on: null,
  scheduled_payment: '1169.79',
} as DebtOut;

const SCHEDULE = {
  debt_id: 'n1',
  citation: 'level-payment amortization, hestia_sim.finance.amortization',
  next_interest: '985.61',
  next_principal: '184.18',
} as ScheduleOut;

describe('MortgagePaymentOffer', () => {
  it('offers the engine pair with its citation and records through the note', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE]);
    vi.spyOn(api, 'debtSchedule').mockResolvedValue(SCHEDULE);
    const record = vi.spyOn(api, 'recordDebtPayment').mockResolvedValue({} as never);
    const onRecorded = vi.fn();
    render(
      <MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={onRecorded} />,
    );
    await waitFor(() => {
      expect(
        screen.getByText(/\$985\.61 interest, \$184\.18 principal, \$1,169\.79 together/),
      ).toBeDefined();
    });
    expect(screen.getByText(/hestia_sim\.finance\.amortization/)).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Record through First Federal' }));
    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('n1', {
        paid_on: '2026-08-28',
        interest: null,
        principal: null,
        extra_principal: '0',
        escrow: '0',
        post_to_ledger: true,
      });
    });
    await waitFor(() => {
      expect(onRecorded).toHaveBeenCalled();
    });
  });

  it('multi-lien picks the note explicitly', async () => {
    const junior = { ...NOTE, id: 'n2', lender: 'Second Street' } as DebtOut;
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE, junior]);
    vi.spyOn(api, 'debtSchedule').mockImplementation((debtId) =>
      Promise.resolve(
        debtId === 'n1'
          ? SCHEDULE
          : ({
              ...SCHEDULE,
              debt_id: 'n2',
              next_interest: '100.00',
              next_principal: '50.00',
            } as ScheduleOut),
      ),
    );
    const record = vi.spyOn(api, 'recordDebtPayment').mockResolvedValue({} as never);
    render(<MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByLabelText('Which note')).toBeDefined();
    });
    fireEvent.change(screen.getByLabelText('Which note'), { target: { value: 'n2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record through Second Street' }));
    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('n2', expect.objectContaining({ post_to_ledger: true }));
    });
  });

  it('names the path without a date, but promises no figures', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE]);
    const scheduleSpy = vi.spyOn(api, 'debtSchedule').mockResolvedValue(SCHEDULE);
    render(<MortgagePaymentOffer propertyId="p1" occurredOn="" onRecorded={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/This looks like a note payment/)).toBeDefined();
    });
    // A split is a fact about a period. With no date there is no period, so
    // the engine is not asked and no figure is shown (#99).
    expect(scheduleSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Record through/ })).toBeNull();
    expect(screen.queryByText(/interest,/)).toBeNull();
  });

  it('asks the engine as of the date being recorded, and follows it', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE]);
    const scheduleSpy = vi
      .spyOn(api, 'debtSchedule')
      .mockImplementation((_id, asOf) =>
        Promise.resolve(
          asOf === '2026-06-01'
            ? ({ ...SCHEDULE, next_interest: '984.84', next_principal: '185.02' } as ScheduleOut)
            : SCHEDULE,
        ),
      );
    const { rerender } = render(
      <MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={vi.fn()} />,
    );
    await waitFor(() => {
      expect(screen.getByText(/\$985\.61 interest/)).toBeDefined();
    });
    expect(scheduleSpy).toHaveBeenCalledWith('n1', '2026-08-28');
    rerender(<MortgagePaymentOffer propertyId="p1" occurredOn="2026-06-01" onRecorded={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByText(/\$984\.84 interest/)).toBeDefined();
    });
    expect(scheduleSpy).toHaveBeenCalledWith('n1', '2026-06-01');
  });

  it('renders nothing without a live amortizing note', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([
      { ...NOTE, paid_off_on: '2026-06-30' } as DebtOut,
      { ...NOTE, id: 'n3', scheduled_payment: null } as DebtOut,
    ]);
    const scheduleSpy = vi.spyOn(api, 'debtSchedule');
    const { container } = render(
      <MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={vi.fn()} />,
    );
    await waitFor(() => {
      expect(api.listDebts).toHaveBeenCalled();
    });
    expect(container.firstElementChild).toBeNull();
    expect(scheduleSpy).not.toHaveBeenCalled();
  });

  it('a consumed schedule offers nothing', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE]);
    vi.spyOn(api, 'debtSchedule').mockResolvedValue({
      ...SCHEDULE,
      next_interest: null,
      next_principal: null,
    } as ScheduleOut);
    const { container } = render(
      <MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={vi.fn()} />,
    );
    await waitFor(() => {
      expect(api.debtSchedule).toHaveBeenCalled();
    });
    expect(container.firstElementChild).toBeNull();
  });

  it('a schedule that will not load leaves the plain form to do the work', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE]);
    vi.spyOn(api, 'debtSchedule').mockRejectedValue(new Error('schedule unavailable'));
    const { container } = render(
      <MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={vi.fn()} />,
    );
    await waitFor(() => {
      expect(api.debtSchedule).toHaveBeenCalled();
    });
    // The note exists and the date is known, so there is no path to name —
    // and no figures to promise. Silence, and the form below still records.
    await waitFor(() => {
      expect(container.firstElementChild).toBeNull();
    });
  });

  it('keeps the operator\u2019s chosen note when the date changes', async () => {
    const junior = { ...NOTE, id: 'n2', lender: 'Second Street' } as DebtOut;
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE, junior]);
    vi.spyOn(api, 'debtSchedule').mockImplementation((debtId) =>
      Promise.resolve(
        debtId === 'n1'
          ? SCHEDULE
          : ({
              ...SCHEDULE,
              debt_id: 'n2',
              next_interest: '100.00',
              next_principal: '50.00',
            } as ScheduleOut),
      ),
    );
    const { rerender } = render(
      <MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={vi.fn()} />,
    );
    await waitFor(() => {
      expect(screen.getByLabelText('Which note')).toBeDefined();
    });
    fireEvent.change(screen.getByLabelText('Which note'), { target: { value: 'n2' } });
    expect(screen.getByRole('button', { name: 'Record through Second Street' })).toBeDefined();
    rerender(<MortgagePaymentOffer propertyId="p1" occurredOn="2026-07-01" onRecorded={vi.fn()} />);
    // Refetching for a new period must not silently reset which note the
    // operator said they were paying.
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Record through Second Street' })).toBeDefined();
    });
  });

  it('a failed fetch is a quiet no-offer, never a broken form', async () => {
    vi.spyOn(api, 'listDebts').mockRejectedValue(new Error('down'));
    const { container } = render(
      <MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={vi.fn()} />,
    );
    await waitFor(() => {
      expect(api.listDebts).toHaveBeenCalled();
    });
    expect(container.firstElementChild).toBeNull();
  });

  it('a refusal that is not an Error still reads as words', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE]);
    vi.spyOn(api, 'debtSchedule').mockResolvedValue(SCHEDULE);
    vi.spyOn(api, 'recordDebtPayment').mockRejectedValue('the lender hung up');
    render(<MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={vi.fn()} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Record through/ })).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: /Record through/ }));
    await waitFor(() => {
      expect(screen.getByText('the lender hung up').className).toBe('error-note');
    });
  });

  it('a refused recording surfaces its reason and records nothing', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE]);
    vi.spyOn(api, 'debtSchedule').mockResolvedValue(SCHEDULE);
    vi.spyOn(api, 'recordDebtPayment').mockRejectedValue(new Error('already paid this period'));
    const onRecorded = vi.fn();
    render(
      <MortgagePaymentOffer propertyId="p1" occurredOn="2026-08-28" onRecorded={onRecorded} />,
    );
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Record through/ })).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: /Record through/ }));
    await waitFor(() => {
      expect(screen.getByText('already paid this period').className).toBe('error-note');
    });
    expect(onRecorded).not.toHaveBeenCalled();
  });
});
