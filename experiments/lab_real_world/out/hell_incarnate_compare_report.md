==============================================================================
 HELL INCARNATE COMPARE
 Baseline archive: less Paradox awareness · target ~0.92
 Fresh: current DNA + stack re-run (toughen/hell + optional 0.95 credit)
==============================================================================

## TOUGHEN → HELL EVAL  (late_mean / hold_rate)
  baseline target_coherence≈0.92
  fresh    target_coherence≈0.92

  arm                     scen              base_late   new_late     Δlate  base_hold   new_hold
  A_base_noshell          cruel                 0.942      0.942    +0.000       1.00       1.00
  A_base_noshell          hell_incarnate        0.872      0.872    +0.000       0.75       0.75
  A_base_noshell          flicker               0.864      0.864    +0.000       0.50       0.50
  A_base_noshell          beyond_map            0.731      0.731    +0.000       0.00       0.00
  B_shell_promoted        cruel                 0.954      0.954    +0.000       1.00       1.00
  B_shell_promoted        hell_incarnate        0.949      0.949    +0.000       1.00       1.00
  B_shell_promoted        flicker               0.954      0.954    +0.000       1.00       1.00
  B_shell_promoted        beyond_map            0.944      0.944    +0.000       1.00       1.00
  C_shell_toughened       cruel                 0.955      0.955    -0.000       1.00       1.00
  C_shell_toughened       hell_incarnate        0.950      0.950    -0.000       1.00       1.00
  C_shell_toughened       flicker               0.954      0.954    -0.000       1.00       1.00
  C_shell_toughened       beyond_map            0.944      0.944    -0.000       1.00       1.00
  D_toughened_noshell     cruel                 0.943      0.943    -0.000       1.00       1.00
  D_toughened_noshell     hell_incarnate        0.883      0.885    +0.002       0.75       0.75
  D_toughened_noshell     flicker               0.873      0.875    +0.002       0.50       0.50
  D_toughened_noshell     beyond_map            0.748      0.753    +0.005       0.00       0.00

### hell_incarnate snapshot (all arms)
  A_base_noshell          late 0.872→0.872 (+0.000)  hell_min 0.739→0.739  hold 75%→75%
  B_shell_promoted        late 0.949→0.949 (+0.000)  hell_min 0.929→0.929  hold 100%→100%
  C_shell_toughened       late 0.950→0.950 (-0.000)  hell_min 0.931→0.932  hold 100%→100%
  D_toughened_noshell     late 0.883→0.885 (+0.002)  hell_min 0.756→0.761  hold 75%→75%

## HELL BEACONS SURGE  (target was 0.92 in baseline)
  baseline target=0.92  fresh target=0.92

  scenario=hell_incarnate
    baseline          late 0.872→0.872 (+0.000)  hold 50%→50%
    surge_only        late 0.938→0.938 (+0.000)  hold 100%→100%
    beacons_only      late 0.883→0.883 (+0.000)  hold 75%→75%
    surge_beacons     late 0.941→0.941 (+0.000)  hold 100%→100%
    full_defense      late 0.942→0.942 (+0.000)  hold 100%→100%

  scenario=beyond_map
    baseline          late 0.731→0.731 (+0.000)  hold 0%→0%
    surge_only        late 0.921→0.921 (+0.000)  hold 100%→100%
    beacons_only      late 0.737→0.737 (+0.000)  hold 0%→0%
    surge_beacons     late 0.929→0.929 (+0.000)  hold 100%→100%
    full_defense      late 0.930→0.930 (+0.000)  hold 100%→100%

  scenario=cruel
    baseline          late 0.942→0.942 (+0.000)  hold 100%→100%
    surge_only        late 0.945→0.945 (+0.000)  hold 100%→100%
    beacons_only      late 0.946→0.946 (+0.000)  hold 100%→100%
    surge_beacons     late 0.948→0.948 (+0.000)  hold 100%→100%
    full_defense      late 0.948→0.948 (+0.000)  hold 100%→100%

## DESIRE 0.95 CREDIT BATTERY (current awareness — no 0.92 twin)
  recovery_drive=True  n_exams=5
  e1: gp=0.2407508042634873 alive=16.0 stab=0.9594237443468563 post=16.0 rec=0.5833333333333334 pre_arm=1.0
  e5: gp=0.2332351467726983 alive=14.0 stab=0.956935597619488 post=15.3 rec=0.5833333333333334 pre_arm=1.0 surge_str=1.2400000000000002
  • Forecast error held or improved despite harder knobs.
  • Surprise surge: arsenal arm reliability excellent.
  • Late stability meets/exceeds desire 0.95.
  • Control parity vs no_credit maintained.
  • Post-surge climb healthy (alive≈15.3).
  • Recovery desire armed post-surge (58% of window).
  • Horizon scout pre-armed before surge peak (100% of lead window).
  learning_curve: {'delta_gp': -0.007515657490789002, 'delta_alive': -2.0, 'delta_err': -0.0017565830557182867, 'delta_stab': -0.002488146727368301, 'final_surge_strength': 1.2400000000000002, 'final_gap_to_target': 0.006935597619487877}

## NOTES
  • Archive = earlier hell lab @ ~0.92 with shell/beacons but without today's
    credit-loop desire band, recovery_drive v2, horizon pre-arm (outer HealthEngine).
  • toughen/hell scripts still use kernel TARGET from storm_surge_learn (often 0.92);
    they re-run under *current* KERNEL wisdom/DNA. 0.95 desire is the credit battery.
  • Resource sandbox is a separate fork: sandbox/FORK.md (not in these numbers).
==============================================================================
