import { createApi } from '@reduxjs/toolkit/query/react';
import cryptodogeLazyBaseQuery from './cryptodogeLazyBaseQuery';

export const baseQuery = cryptodogeLazyBaseQuery({});

export default createApi({
  reducerPath: 'cryptodogeApi',
  baseQuery,
  endpoints: () => ({}),
});
