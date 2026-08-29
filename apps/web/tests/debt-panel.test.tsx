import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DebtPanel } from '../src/components/DebtPanel';
import { api, type DebtOut, type ScheduleOut } from '../src/lib/api';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const TODAY = '2026-08-28';

const NOTE: DebtOut = {
  id: 'n1',
  property_id: 'p1',
  property_label: '998 Monmouth St',
  entity_id: 'e1',
  lender: 'First Federal',
  kind: 'conventional_mortgage',
  lien_position: 1,
  original_principal: '190000.00',
  interest_rate: '0.06250000',
  term_months: 360,
  originated_on: '2024-02-01',
  first_payment_on: null,
  matures_on: null,
  amortization: 'fully_amortizing',
  amortization_months: null,
  scheduled_payment: '1169.79',
  payments_recorded: 2,
  principal_paid: '360.00',
  interest_paid: '1979.58',
  paid_off_on: null,
  is_recourse: true,
  has_due_on_sale: true,
  prepayment: 'none',
  prepayment_terms: null,
  rate_index: null,
  rate_adjusts_on: null,
  escrows_taxes: false,
  escrows_insurance: false,
  document_id: null,
};

const SCHEDULE: ScheduleOut = {
  debt_id: 'n1',
  scheduled_payment: '1169.79',
  citation: 'engines/amortization',
  total_interest: '200934.62',
  next_month: 32,
  next_interest: '985.61',
  next_principal: '184.18',
  rows: [
    {
      month: 31,
      payment: '1169.79',
      interest: '986.57',
      principal: '183.22',
      balance: '189261.42',
    },
    {
      month: 32,
      payment: '1169.79',
      interest: '985.61',
      principal: '184.18',
      balance: '189077.24',
    },
  ],
};

const arrange = (debts: DebtOut[], schedule: ScheduleOut | null = SCHEDULE) => {
  vi.spyOn(api, 'listDebts').mockResolvedValue(debts);
  const scheduleSpy = vi.spyOn(api, 'debtSchedule');
  if (schedule === null) {
    scheduleSpy.mockRejectedValue(new Error('no schedule'));
  } else {
    scheduleSpy.mockResolvedValue(schedule);
  }
  return { scheduleSpy };
};

describe('DebtPanel', () => {
  it('renders the record: the note, the counters, and the engine suggestion', async () => {
    arrange([NOTE]);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    expect(screen.getByText('Loading…')).toBeDefined();
    await waitFor(() => {
      expect(screen.getByText('First Federal')).toBeDefined();
    });
    expect(screen.getByText('conventional mortgage', { selector: '.pill' })).toBeDefined();
    expect(
      screen.getByText(/\$190,000\.00 at 6\.250% over 360 months — originated Feb 1, 2024/),
    ).toBeDefined();
    expect(screen.getByText('$1,169.79/mo')).toBeDefined();
    expect(
      screen.getByText(/2 payments — \$360\.00 principal, \$1,979\.58 interest/),
    ).toBeDefined();
    await waitFor(() => {
      expect(screen.getByText(/month 32 — \$985\.61 interest, \$184\.18 principal/)).toBeDefined();
    });
  });

  it('opens the schedule under its citation with the rows and the total', async () => {
    arrange([NOTE]);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /The schedule/ })).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: /The schedule/ }));
    expect(screen.getByText('engines/amortization')).toBeDefined();
    expect(screen.getByText(/\$200,934\.62 of interest over the remaining term/)).toBeDefined();
    expect(screen.getByText('$189,077.24')).toBeDefined();
  });

  it('pre-fills the payment from the engine split and records an edited one', async () => {
    arrange([NOTE]);
    const record = vi.spyOn(api, 'recordDebtPayment').mockResolvedValue({} as never);
    const onChanged = vi.fn();
    render(<DebtPanel propertyId="p1" today={TODAY} onChanged={onChanged} />);
    await waitFor(() => {
      expect(screen.getByLabelText('Interest')).toBeDefined();
    });
    await waitFor(() => {
      expect((screen.getByLabelText('Interest') as HTMLInputElement).value).toBe('985.61');
    });
    expect((screen.getByLabelText('Principal') as HTMLInputElement).value).toBe('184.18');
    fireEvent.change(screen.getByLabelText('Principal'), { target: { value: '200.00' } });
    fireEvent.change(screen.getByLabelText('Paid on'), { target: { value: '2026-09-01' } });
    fireEvent.change(screen.getByLabelText('Extra principal'), { target: { value: '100.00' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record the payment' }));
    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('n1', {
        paid_on: '2026-09-01',
        // Interest was never touched, so it travels as null and the server
        // splits September by September's row — the figure on screen was a
        // suggestion, never a statement (#99).
        interest: null,
        principal: '200.00',
        extra_principal: '100.00',
        escrow: '0',
        post_to_ledger: true,
      });
    });
    await waitFor(() => {
      expect(onChanged).toHaveBeenCalled();
    });
  });

  it('a cleared split travels as null so the engine decides, and the ledger opt-out holds', async () => {
    arrange([NOTE]);
    const record = vi.spyOn(api, 'recordDebtPayment').mockResolvedValue({} as never);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect((screen.getByLabelText('Interest') as HTMLInputElement).value).toBe('985.61');
    });
    fireEvent.change(screen.getByLabelText('Interest'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Principal'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Extra principal'), { target: { value: '' } });
    fireEvent.click(screen.getByLabelText(/Post to the ledger/));
    fireEvent.click(screen.getByRole('button', { name: 'Record the payment' }));
    await waitFor(() => {
      expect(record).toHaveBeenCalledWith('n1', {
        paid_on: TODAY,
        interest: null,
        principal: null,
        extra_principal: '0',
        escrow: '0',
        post_to_ledger: false,
      });
    });
  });

  it('asks the engine for the split AS OF the date being recorded', async () => {
    const { scheduleSpy } = arrange([NOTE]);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(scheduleSpy).toHaveBeenCalledWith('n1', TODAY);
    });
    // Backdating a catch-up payment re-asks for THAT period's row rather
    // than keeping the figures for the day the panel happened to load.
    fireEvent.change(screen.getByLabelText('Paid on'), { target: { value: '2026-06-01' } });
    await waitFor(() => {
      expect(scheduleSpy).toHaveBeenCalledWith('n1', '2026-06-01');
    });
  });

  it('re-prefills from the backdated period, and still states nothing', async () => {
    vi.spyOn(api, 'listDebts').mockResolvedValue([NOTE]);
    vi.spyOn(api, 'debtSchedule').mockImplementation((_id, asOf) =>
      Promise.resolve(
        asOf === '2026-06-01'
          ? ({
              ...SCHEDULE,
              next_month: 6,
              next_interest: '984.84',
              next_principal: '185.02',
            } as ScheduleOut)
          : SCHEDULE,
      ),
    );
    const record = vi.spyOn(api, 'recordDebtPayment').mockResolvedValue({} as never);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect((screen.getByLabelText('Interest') as HTMLInputElement).value).toBe('985.61');
    });
    fireEvent.change(screen.getByLabelText('Paid on'), { target: { value: '2026-06-01' } });
    // The suggestion follows the date: June's row, not August's.
    await waitFor(() => {
      expect((screen.getByLabelText('Interest') as HTMLInputElement).value).toBe('984.84');
    });
    expect((screen.getByLabelText('Principal') as HTMLInputElement).value).toBe('185.02');
    fireEvent.click(screen.getByRole('button', { name: 'Record the payment' }));
    await waitFor(() => {
      expect(record).toHaveBeenCalledWith(
        'n1',
        expect.objectContaining({ paid_on: '2026-06-01', interest: null, principal: null }),
      );
    });
  });

  it('records a payoff dated today', async () => {
    arrange([NOTE]);
    const payoff = vi.spyOn(api, 'payoffDebt').mockResolvedValue({} as never);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Record payoff as of Aug 28, 2026/ }),
      ).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: /Record payoff as of Aug 28, 2026/ }));
    await waitFor(() => {
      expect(payoff).toHaveBeenCalledWith('n1', { paid_off_on: TODAY });
    });
  });

  it('an interest-only note states its honest gap and never fetches a schedule', async () => {
    const { scheduleSpy } = arrange([
      { ...NOTE, id: 'n2', amortization: 'interest_only', scheduled_payment: null },
    ]);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByText(/none — a interest only note gets no inferred split/)).toBeDefined();
    });
    expect(scheduleSpy).not.toHaveBeenCalled();
    expect(screen.queryByText(/Next per the engine/)).toBeNull();
  });

  it('a paid-off note is a record, not a workbench', async () => {
    const { scheduleSpy } = arrange([{ ...NOTE, paid_off_on: '2026-06-30' }]);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByText('paid off Jun 30, 2026').className).toBe('pill pill--ok');
    });
    expect(scheduleSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Record the payment' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Record payoff/ })).toBeNull();
  });

  it('the record stands when the schedule cannot be fetched', async () => {
    arrange([NOTE], null);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByText('First Federal')).toBeDefined();
    });
    expect(screen.queryByText(/Next per the engine/)).toBeNull();
    // The form still records; empty fields defer to the server's engine split.
    expect((screen.getByLabelText('Interest') as HTMLInputElement).value).toBe('');
  });

  it('records a mortgage from the entry form, nameless lender as null', async () => {
    arrange([]);
    const create = vi.spyOn(api, 'createDebt').mockResolvedValue({} as never);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByText(/No notes on record/)).toBeDefined();
    });
    fireEvent.change(screen.getByLabelText('Original principal'), {
      target: { value: '190000.00' },
    });
    fireEvent.change(screen.getByLabelText(/Annual rate/), { target: { value: '0.0625' } });
    fireEvent.change(screen.getByLabelText('Originated'), { target: { value: '2024-02-01' } });
    fireEvent.change(screen.getByLabelText('Kind'), { target: { value: 'seller_financing' } });
    fireEvent.change(screen.getByLabelText('Term (months)'), { target: { value: '180' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record the mortgage' }));
    await waitFor(() => {
      expect(create).toHaveBeenCalledWith({
        lender: null,
        kind: 'seller_financing',
        original_principal: '190000.00',
        interest_rate: '0.0625',
        term_months: 180,
        originated_on: '2024-02-01',
        amortization: 'fully_amortizing',
        lien_position: 1,
        is_recourse: true,
        has_due_on_sale: true,
        prepayment: 'none',
        escrows_taxes: false,
        escrows_insurance: false,
        property_id: 'p1',
      });
    });
  });

  it('a named lender travels by name', async () => {
    arrange([]);
    const create = vi.spyOn(api, 'createDebt').mockResolvedValue({} as never);
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByLabelText('Lender')).toBeDefined();
    });
    fireEvent.change(screen.getByLabelText('Lender'), { target: { value: 'First Federal' } });
    fireEvent.change(screen.getByLabelText('Original principal'), { target: { value: '1000' } });
    fireEvent.change(screen.getByLabelText(/Annual rate/), { target: { value: '0.05' } });
    fireEvent.change(screen.getByLabelText('Originated'), { target: { value: '2026-01-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record the mortgage' }));
    await waitFor(() => {
      expect(create).toHaveBeenCalledWith(expect.objectContaining({ lender: 'First Federal' }));
    });
  });

  it('names the nameless lender and stays quiet about a consumed schedule', async () => {
    arrange([{ ...NOTE, lender: null }], {
      ...SCHEDULE,
      next_month: null,
      next_interest: null,
      next_principal: null,
      rows: [],
    });
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByText('Unnamed lender')).toBeDefined();
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /The schedule/ })).toBeDefined();
    });
    // A schedule with nothing next offers no suggestion sentence.
    expect(screen.queryByText(/Next per the engine/)).toBeNull();
    expect((screen.getByLabelText('Interest') as HTMLInputElement).value).toBe('');
  });

  it('a failure that is not an Error still reads as words', async () => {
    vi.spyOn(api, 'listDebts').mockRejectedValue('the wire snapped');
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByText('the wire snapped').className).toBe('error-note');
    });
  });

  it('an action failure that is not an Error still reads as words', async () => {
    arrange([NOTE]);
    vi.spyOn(api, 'payoffDebt').mockRejectedValue('the lender hung up');
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Record payoff/ })).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: /Record payoff/ }));
    await waitFor(() => {
      expect(screen.getByText('the lender hung up').className).toBe('error-note');
    });
  });

  it('surfaces a load failure as an error note', async () => {
    vi.spyOn(api, 'listDebts').mockRejectedValue(new Error('the API is down'));
    render(<DebtPanel propertyId="p1" today={TODAY} />);
    await waitFor(() => {
      expect(screen.getByText('the API is down').className).toBe('error-note');
    });
  });

  it('surfaces an action failure and does not call onChanged', async () => {
    arrange([NOTE]);
    vi.spyOn(api, 'payoffDebt').mockRejectedValue(new Error('already paid off'));
    const onChanged = vi.fn();
    render(<DebtPanel propertyId="p1" today={TODAY} onChanged={onChanged} />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Record payoff/ })).toBeDefined();
    });
    fireEvent.click(screen.getByRole('button', { name: /Record payoff/ }));
    await waitFor(() => {
      expect(screen.getByText('already paid off')).toBeDefined();
    });
    expect(onChanged).not.toHaveBeenCalled();
  });
});
