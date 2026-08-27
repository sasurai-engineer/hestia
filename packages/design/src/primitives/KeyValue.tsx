import { Fragment, type ReactNode } from 'react';

type KeyValueProps = {
  items: readonly { key: string; value: ReactNode }[];
};

export function KeyValue({ items }: KeyValueProps) {
  return (
    <dl className="kv">
      {items.map((item) => (
        <Fragment key={item.key}>
          <dt>{item.key}</dt>
          <dd>{item.value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
