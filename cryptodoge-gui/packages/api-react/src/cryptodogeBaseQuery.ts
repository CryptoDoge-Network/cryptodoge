import { BaseQueryFn } from '@reduxjs/toolkit/query/react';
import Client, { Service } from '@cryptodoge/api';

type Options = {
  client: Client;
  service: Service;
};

export default function cryptodogeBaseQuery(options: Options): BaseQueryFn<
  {
    command: string; 
    args?: any[],
  },
  unknown,
  unknown,
  {},
  {
    timestamp: number;
    command: string;
    args?: any[];
  }
> {
  const { 
    client, 
    service: Service,
  } = options;

  const service = new Service(client);

  return async ({ command, args = [] }) => {
    const meta = { 
      timestamp: Date.now(),
      command,
      args,
    };

    try {
      return { 
        data: await service[command](...args),
        meta,
      };
    } catch(error) {
      return { 
        error,
        meta,
      };
    }
  };
}
