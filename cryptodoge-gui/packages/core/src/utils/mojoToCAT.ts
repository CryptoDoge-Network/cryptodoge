import Big from 'big.js';
import Unit from '../constants/Unit';
import cryptodogeFormatter from './cryptodogeFormatter';

export default function mojoToCAT(mojo: string | number | Big): number {
  return cryptodogeFormatter(mojo, Unit.MOJO)
    .to(Unit.CAT)
    .toNumber();
}
