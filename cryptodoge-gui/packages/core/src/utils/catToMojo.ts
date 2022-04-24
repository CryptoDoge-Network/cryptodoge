import Big from 'big.js';
import Unit from '../constants/Unit';
import cryptodogeFormatter from './cryptodogeFormatter';

export default function catToMojo(cat: string | number | Big): number {
  return cryptodogeFormatter(cat, Unit.CAT)
    .to(Unit.MOJO)
    .toNumber();
}
