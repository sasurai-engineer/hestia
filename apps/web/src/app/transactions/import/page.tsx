'use client';

import { useCallback, useEffect, useState } from 'react';
import { ReviewQueueTable } from '../../../components/ReviewQueueTable';
import {
  type AcceptIn,
  api,
  type BankAccountOut,
  type EntityOut,
  type ImportSummary,
  type StagedTransaction,
} from '../../../lib/api';
import { acceptSplits, type NoteSplit, noteSplit } from '../../../lib/mortgage-split';

export default function ImportPage() {
  const [accounts, setAccounts] = useState<BankAccountOut[]>([]);
  const [entities, setEntities] = useState<EntityOut[]>([]);
  const [accountId, setAccountId] = useState('');
  const [entityId, setEntityId] = useState('');
  const [nickname, setNickname] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [queue, setQueue] = useState<StagedTransaction[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listBankAccounts(), api.listEntities()])
      .then(([bankAccounts, owners]) => {
        setAccounts(bankAccounts);
        setEntities(owners);
        setAccountId(bankAccounts[0]?.id ?? '');
        setEntityId(owners[0]?.id ?? '');
      })
      .catch((caught: unknown) => {
        setError(caught instanceof Error ? caught.message : String(caught));
      });
  }, []);

  const refreshQueue = useCallback(async (batchId: string) => {
    setQueue(await api.reviewQueue(batchId, 'pending'));
  }, []);

  // The engine splits for each (property, posted_on) in the queue. The DATE
  // is half the key: a statement imported in August carries rows from May,
  // June and July, and each row's split is the split for ITS period — the
  // level payment is identical across periods, so a period-blind split
  // matches the amount exactly and posts the wrong figures silently (#99).
  // A property with no live amortizing note maps to an empty list, which is
  // the honest no-offer state.
  const [splitsByRow, setSplitsByRow] = useState<Record<string, NoteSplit[]>>({});
  useEffect(() => {
    const pending = [
      ...new Set(
        queue
          .filter((row) => row.suggested_property_id)
          .map((row) => `${String(row.suggested_property_id)}|${row.posted_on}`),
      ),
    ].filter((key) => !(key in splitsByRow));
    for (const key of pending) {
      const [propertyId, postedOn] = key.split('|') as [string, string];
      void (async () => {
        try {
          const debts = await api.listDebts({ propertyId });
          const loaded: NoteSplit[] = [];
          for (const debt of debts) {
            if (debt.paid_off_on !== null || debt.scheduled_payment === null) continue;
            const split = noteSplit(debt, await api.debtSchedule(debt.id, postedOn));
            if (split) loaded.push(split);
          }
          setSplitsByRow((current) => ({ ...current, [key]: loaded }));
        } catch {
          // No offer is an honest state; plain accept still works.
          setSplitsByRow((current) => ({ ...current, [key]: [] }));
        }
      })();
    }
  }, [queue, splitsByRow]);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      let target = accountId;
      if (target === '' && nickname.trim() !== '' && entityId !== '') {
        const account = await api.createBankAccount({
          entity_id: entityId,
          nickname: nickname.trim(),
          kind: 'checking',
          invert_amounts: false,
        });
        target = account.id;
        setAccounts([...accounts, account]);
        setAccountId(account.id);
      }
      const result = await api.importStatement(target, file);
      setSummary(result);
      await refreshQueue(result.batch_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const decide = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      if (summary) await refreshQueue(summary.batch_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  };

  return (
    <>
      <h1 className="page-title">Import a statement</h1>
      <p className="page-subtitle">
        Export CSV or OFX from any bank — no third party ever sees your transactions. Every
        suggested category passes your review before it touches the ledger, and re-importing an
        overlapping statement is a no-op.
      </p>
      {error ? <p className="error-note">{error}</p> : null}

      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          void upload();
        }}
      >
        <div className="form-row">
          <div className="field">
            <label htmlFor="imp-account">Bank account</label>
            <select
              id="imp-account"
              value={accountId}
              onChange={(event) => {
                setAccountId(event.target.value);
              }}
            >
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.nickname}
                  {account.account_last4 ? ` ···${account.account_last4}` : ''}
                </option>
              ))}
              <option value="">+ new account…</option>
            </select>
          </div>
          {accountId === '' ? (
            <>
              <div className="field">
                <label htmlFor="imp-nickname">Account nickname</label>
                <input
                  id="imp-nickname"
                  required
                  value={nickname}
                  onChange={(event) => {
                    setNickname(event.target.value);
                  }}
                />
              </div>
              <div className="field">
                <label htmlFor="imp-entity">Owned by</label>
                <select
                  id="imp-entity"
                  required
                  value={entityId}
                  onChange={(event) => {
                    setEntityId(event.target.value);
                  }}
                >
                  {entities.map((entity) => (
                    <option key={entity.id} value={entity.id}>
                      {entity.name}
                    </option>
                  ))}
                </select>
              </div>
            </>
          ) : null}
          <div className="field">
            <label htmlFor="imp-file">Statement file (.csv / .ofx / .qfx)</label>
            <input
              id="imp-file"
              type="file"
              required
              accept=".csv,.ofx,.qfx"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
              }}
            />
          </div>
        </div>
        <button className="button" type="submit" disabled={busy || !file}>
          {busy ? 'Importing…' : 'Import'}
        </button>
      </form>

      {summary ? (
        <section className="section">
          <h2 className="section__title">Review queue</h2>
          <p className="muted">
            {summary.staged} staged · {summary.duplicates} already known · {summary.suggested}{' '}
            suggested
          </p>
          <ReviewQueueTable
            rows={queue}
            onAccept={(txnId, category) => {
              void decide(() =>
                api.acceptBankTransaction(txnId, {
                  category: category as NonNullable<AcceptIn['category']>,
                }),
              );
            }}
            onExclude={(txnId) => {
              void decide(() => api.excludeBankTransaction(txnId));
            }}
            noteSplits={(row) =>
              row.suggested_property_id
                ? (splitsByRow[`${row.suggested_property_id}|${row.posted_on}`] ?? [])
                : []
            }
            onAcceptSplit={(row, split) => {
              void decide(() =>
                api.acceptBankTransaction(row.id, {
                  splits: acceptSplits(row.amount, split),
                  ...(row.suggested_property_id ? { property_id: row.suggested_property_id } : {}),
                }),
              );
            }}
          />
        </section>
      ) : null}
    </>
  );
}
