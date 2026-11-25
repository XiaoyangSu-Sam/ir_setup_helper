import assert from 'node:assert/strict';
import {test} from 'node:test';
import {inspectTeamProgress} from '../../registration/team-progress.mjs';

const series = 'Creventic 992 Endurance Cup';
const car = 'Porsche 911 Cup (992.2)';
const venue = 'Circuit de Spa-Francorchamps';
const track = venue + ' Endurance';
const now = Date.parse('2026-11-24T21:00:00Z');

function snapshot({visibleCar = car, banner = '', rows = [], panel = true, currentTrack = track, shownSeries = series, path = '/go-racing'} = {}) {
  const nodes = [];
  function add(type, name, parent = -1, id = '') {
    const index = nodes.length;
    nodes.push({index, parent, type: 'ControlType.' + type, name, id});
    return index;
  }
  add('Text', shownSeries);
  const race = add('Group', '');
  add('Text', 'Next Race @ ' + currentTrack, race);
  add('Text', banner, race);
  add('Button', 'Register', race);
  const carCard = add('Group', '');
  const selectedCar = add('Group', 'Selected Car', add('Group', '', carCard));
  add('Text', 'Selected Car', selectedCar);
  add('Text', visibleCar, carCard);
  add('Button', '', add('Group', '', add('Group', '', carCard)), 'favorite_cars-208');
  const venueGroup = add('Group', '');
  add('Text', venue, venueGroup);
  add('Button', '', add('Group', '', add('Group', '', venueGroup)), 'favorite_tracks-525');
  if (panel) {
    const eligibility = add('Group', 'Eligibility', -1, 'accordion-panel-:r178:');
    for (const row of rows) {
      const group = add('Group', '', eligibility);
      for (const fragment of row) add('Text', fragment, group);
      add('Separator', '', eligibility);
    }
  }
  return {ok: true, observedAt: new Date(now).toISOString(), url: 'https://members-ng.iracing.com/web/racing/official/series-list/6777' + path, nodes};
}

const license = ['Your license is', 'D 4.0', 'or above.', 'Results affect your', 'B', 'license'];
const trackOwned = ['You licensed', venue];
const raceEligible = ['Eligible for race session!'];
const carOwned = ['You licensed', car];
const needsCar = ['You need to purchase the content license for', 'a car', 'in this event'];
const needsTrack = ['You need to purchase the content license for', venue];

function check(options, plan = {}) {
  return inspectTeamProgress({series, car, revision: 1, ...plan}, snapshot(options), now);
}

test('actual Spa text identifies a missing car even with green eligibility', () => {
  const report = check({
    banner: 'You are eligible to compete, but you need to purchase the content license for ' + car,
    rows: [license, trackOwned, needsCar, raceEligible],
  });
  assert.equal(report.eligibility.status, 'blocked');
  assert.deepEqual(report.eligibility.car, {name: car, status: 'missing'});
  assert.deepEqual(report.eligibility.track, {name: track, status: 'owned'});
  assert.deepEqual(report.eligibility.license, {requirement: 'D 4.0', status: 'met'});
  assert.equal(report.registrationConfirmed, false);
});

test('a missing track is reported separately even when the selected car is owned', () => {
  const {eligibility} = check({rows: [license, needsTrack, carOwned, raceEligible]});
  assert.equal(eligibility.status, 'blocked');
  assert.equal(eligibility.track.status, 'missing');
  assert.equal(eligibility.car.status, 'owned');
});

test('a positive result requires affirmative ownership of both and a qualifying license', () => {
  const {eligibility} = check({rows: [license, trackOwned, carOwned, raceEligible]});
  assert.equal(eligibility.status, 'met');
  assert.equal(check({rows: [trackOwned, carOwned]}).eligibility.status, 'unknown');
  const blocked = check({rows: [license, trackOwned, carOwned, ['Ineligible for race session!']]}).eligibility;
  assert.equal(blocked.status, 'blocked');
  assert.equal(blocked.license.status, 'met');
  const lowLicense = check({rows: [['Your license is below', 'D 4.0.'], trackOwned, carOwned]}).eligibility;
  assert.deepEqual(lowLicense.license, {requirement: 'D 4.0', status: 'unmet'});
});

test('the purchase banner can name both missing items', () => {
  const {eligibility} = check({
    banner: 'You are eligible to compete, but you need to purchase the content licenses for ' + car + ' and ' + venue,
    rows: [license, raceEligible],
  });
  assert.equal(eligibility.car.status, 'missing');
  assert.equal(eligibility.track.status, 'missing');
});

test('actual Mazda wording confirms the selected car when the race summary also confirms eligibility', () => {
  const purchased = ['You purchased the content license for', '1 car competing', 'in this event'];
  const rows = [license, trackOwned, purchased, raceEligible];
  const banner = 'You are eligible to race in this series!';
  assert.equal(check({banner, rows}).eligibility.car.status, 'owned');
  assert.equal(check({rows}).eligibility.car.status, 'unknown');
  assert.equal(check({visibleCar: 'Another Car', banner, rows}).eligibility.car.status, 'unknown');
});

test('a different selected or unconfirmed car stays unknown', () => {
  assert.equal(check({visibleCar: 'Another Car', rows: [license, trackOwned, needsCar]}).eligibility.car.status, 'unknown');
  assert.equal(check({rows: [license, trackOwned, ['You licensed', 'a car', 'in this event'], raceEligible]}).eligibility.car.status, 'unknown');
  assert.equal(check({rows: [license, trackOwned, [...carOwned, 'GT3'], raceEligible]}).eligibility.car.status, 'unknown');
});

test('a series-only draft can read the current selected car without completing the roster', () => {
  const {eligibility} = check({rows: [license, trackOwned, carOwned]}, {car: ''});
  assert.equal(eligibility.car.name, car);
  assert.equal(eligibility.status, 'met');
});

test('old drafts using the official calendar name still match the actual Spa series', () => {
  const {eligibility} = check({rows: [license, trackOwned, needsCar]}, {series: '992 Endurance Cup'});
  assert.equal(eligibility.car.status, 'missing');
});

test('a wrong page, missing panel, wrong venue or conflicting evidence stays unknown', () => {
  assert.equal(check({path: '/series-insights', rows: [license, trackOwned, carOwned]}).eligibility.status, 'unknown');
  assert.equal(check({shownSeries: 'Other Series', rows: [license, trackOwned, carOwned]}).eligibility.status, 'unknown');
  assert.equal(check({panel: false}).eligibility.status, 'unknown');
  assert.equal(check({currentTrack: 'Daytona International Speedway Road Course', rows: [license, trackOwned, carOwned]}).eligibility.track.status, 'unknown');
  assert.equal(check({rows: [license, trackOwned, needsTrack, carOwned]}).eligibility.track.status, 'unknown');
});
