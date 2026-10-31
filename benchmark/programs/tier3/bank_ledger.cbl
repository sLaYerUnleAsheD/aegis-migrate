      * BANK LEDGER (tier 3): two-level control break, signed balances
      * Record (14 bytes): BRANCH X(2) ACCT X(4) TYPE X AMT 9(5)V99
      * D adds to the account balance, C subtracts (it may go below
      * zero), any other type is skipped. A line prints when the account
      * changes and again when the branch changes (a branch change also
      * ends the account). Input need not be sorted.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BANKLEDG.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LEDGER-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  LEDGER-FILE.
       01  LEDGER-REC.
           05 BR-BRANCH      PIC X(2).
           05 BR-ACCT        PIC X(4).
           05 BR-TYPE        PIC X(1).
           05 BR-AMT         PIC 9(5)V99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X         VALUE "N".
           88 INPUT-DONE                   VALUE "Y".
       01  WS-FIRST-FLAG     PIC X         VALUE "Y".
           88 FIRST-RECORD                 VALUE "Y".
       01  WS-PREV-BRANCH    PIC X(2)      VALUE SPACES.
       01  WS-PREV-ACCT      PIC X(4)      VALUE SPACES.
       01  WS-BAL            PIC S9(7)V99  VALUE 0.
       01  WS-BRANCH-TOT     PIC S9(9)V99  VALUE 0.
       01  WS-GRAND-TOT      PIC S9(9)V99  VALUE 0.
       01  WS-SKIPPED        PIC 99        VALUE 0.
       01  WS-AMT-ED         PIC ZZ,ZZ9.99.
       01  WS-BAL-ED         PIC -Z,ZZZ,ZZ9.99.
       01  WS-TOT-ED         PIC -ZZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT LEDGER-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           IF NOT FIRST-RECORD
               PERFORM ACCT-BREAK-PARA
               PERFORM BRANCH-BREAK-PARA
           END-IF
           CLOSE LEDGER-FILE
           PERFORM GRAND-PARA
           STOP RUN.

       READ-PARA.
           READ LEDGER-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           IF FIRST-RECORD
               MOVE BR-BRANCH TO WS-PREV-BRANCH
               MOVE BR-ACCT TO WS-PREV-ACCT
               MOVE "N" TO WS-FIRST-FLAG
           ELSE
               IF BR-BRANCH NOT = WS-PREV-BRANCH
                   PERFORM ACCT-BREAK-PARA
                   PERFORM BRANCH-BREAK-PARA
                   MOVE BR-BRANCH TO WS-PREV-BRANCH
                   MOVE BR-ACCT TO WS-PREV-ACCT
               ELSE
                   IF BR-ACCT NOT = WS-PREV-ACCT
                       PERFORM ACCT-BREAK-PARA
                       MOVE BR-ACCT TO WS-PREV-ACCT
                   END-IF
               END-IF
           END-IF
           PERFORM POST-PARA
           PERFORM READ-PARA.

       POST-PARA.
           MOVE BR-AMT TO WS-AMT-ED
           EVALUATE BR-TYPE
               WHEN "D"
                   ADD BR-AMT TO WS-BAL
                   DISPLAY BR-ACCT " D " WS-AMT-ED
               WHEN "C"
                   SUBTRACT BR-AMT FROM WS-BAL
                   DISPLAY BR-ACCT " C " WS-AMT-ED
               WHEN OTHER
                   ADD 1 TO WS-SKIPPED
                   DISPLAY BR-ACCT " ? SKIPPED"
           END-EVALUATE.

       ACCT-BREAK-PARA.
           MOVE WS-BAL TO WS-BAL-ED
           DISPLAY "  ACCOUNT " WS-PREV-ACCT " BALANCE:" WS-BAL-ED
           ADD WS-BAL TO WS-BRANCH-TOT
           MOVE 0 TO WS-BAL.

       BRANCH-BREAK-PARA.
           MOVE WS-BRANCH-TOT TO WS-TOT-ED
           DISPLAY " BRANCH " WS-PREV-BRANCH " TOTAL:" WS-TOT-ED
           ADD WS-BRANCH-TOT TO WS-GRAND-TOT
           MOVE 0 TO WS-BRANCH-TOT.

       GRAND-PARA.
           MOVE WS-GRAND-TOT TO WS-TOT-ED
           DISPLAY "GRAND TOTAL:" WS-TOT-ED
           DISPLAY "SKIPPED: " WS-SKIPPED.