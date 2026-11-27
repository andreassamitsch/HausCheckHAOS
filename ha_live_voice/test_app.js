'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {Activity,mergeText}=require('./app.js');
test('idle stops at ten seconds',()=>{const a=new Activity(0);assert.equal(a.canEnd(9999,10,false),false);assert.equal(a.canEnd(10000,10,false),true);});
test('pending task cannot be interrupted by idle',()=>{const a=new Activity(0);a.input(1000);assert.equal(a.canEnd(12000,10,false),false);assert.equal(a.canEnd(121000,10,true),false);a.output(20000);assert.equal(a.canEnd(29999,10,false),false);assert.equal(a.canEnd(30000,10,false),true);});
test('speaking protects session, countdown starts after audio stops',()=>{const a=new Activity(0);a.speech('assistant',true,1000);assert.equal(a.canEnd(40000,10,false),false);a.speech('assistant',false,41000);assert.equal(a.canEnd(50999,10,false),false);assert.equal(a.canEnd(51000,10,false),true);});
test('speech and remote audio refresh idle',()=>{const a=new Activity(0);a.speech('user',true,8000);assert.equal(a.canEnd(15000,10,false),false);a.speech('user',false,16000);a.output(30000);a.output(39000);assert.equal(a.canEnd(48000,10,false),false);assert.equal(a.canEnd(49000,10,false),true);});
test('transcript chunks and final do not duplicate',()=>{assert.equal(mergeText('Hallo',' Welt'),'Hallo Welt');assert.equal(mergeText('Hallo Welt','Hallo Welt',true),'Hallo Welt');assert.equal(mergeText('Hallo Welt','Welt',true),'Hallo Welt');});
