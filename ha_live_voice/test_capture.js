'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {FirstAudioBuffer}=require('./capture-worklet.js');
function feed(b,v,n=1){const out=[];for(let i=0;i<n;i++){const x=new Float32Array(10).fill(v);const y=new Float32Array(10);b.process(x,y);out.push(y[0]);}return out;}
test('early speech stays local and replays once in order',()=>{const b=new FirstAudioBuffer(100);assert.deepEqual(feed(b,.1,3),[0,0,0]);feed(b,.2,2);b.ready();const out=feed(b,.3,5);assert.ok(out.slice(0,3).every(x=>Math.abs(x-.1)<1e-6));assert.ok(out.slice(3).every(x=>Math.abs(x-.2)<1e-6));assert.equal(b.mode,'drain');});
test('quiet start goes straight to live',()=>{const b=new FirstAudioBuffer(100);feed(b,0,5);b.ready();assert.equal(b.mode,'live');assert.ok(Math.abs(feed(b,.2)[0]-.2)<1e-6);});
test('drains first command then drops only quiet tail and returns to live',()=>{const b=new FirstAudioBuffer(100);feed(b,.1,5);b.ready();const out=feed(b,0,16);assert.equal(out.filter(x=>x>.05).length,5);assert.equal(b.mode,'live');assert.ok(Math.abs(feed(b,.2)[0]-.2)<1e-6);assert.equal(b.samples,0);});
test('bounded buffer aborts instead of silently cutting a command',()=>{const b=new FirstAudioBuffer(100,.2);feed(b,.1,3);assert.equal(b.overflow,true);assert.equal(b.samples,0);b.ready();assert.deepEqual(feed(b,.2),[0]);});
test('no voiced samples skipped during long continuous utterance',()=>{const b=new FirstAudioBuffer(100);feed(b,.1,4);b.ready();const out=feed(b,.2,10);assert.ok(out.slice(0,4).every(x=>Math.abs(x-.1)<1e-6));assert.ok(out.slice(4).every(x=>Math.abs(x-.2)<1e-6));assert.equal(b.mode,'drain');});
