      * OVERFLOW DEMO (tier 3): accumulators that are too small ON PURPOSE.
      * Record (11 bytes): ACCT X(4) | AMT 9(5)V99
      * WS-WRAP-TOTAL has no SIZE ERROR phrase, so overflow behaviour is
      * whatever the compiler does. WS-SAFE-TOTAL uses ON SIZE ERROR and
      * counts the overflows. WS-HALF is truncated, not rounded.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. OVERFLOW.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT AMT-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  AMT-FILE.
       01  AMT-REC.
           05 AR-ACCT        PIC X(4).
           05 AR-AMT         PIC 9(5)V99.

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X        VALUE "N".
           88 INPUT-DONE                  VALUE "Y".
       01  WS-WRAP-TOTAL     PIC 9(5)V99  VALUE 0.
       01  WS-SAFE-TOTAL     PIC 9(5)V99  VALUE 0.
       01  WS-OVERFLOWS      PIC 99       VALUE 0.
       01  WS-COUNT          PIC 99       VALUE 0.
       01  WS-HALF           PIC 9(5)V9   VALUE 0.
       01  WS-AMT-ED         PIC ZZ,ZZ9.99.
       01  WS-WRAP-ED        PIC ZZ,ZZ9.99.
       01  WS-SAFE-ED        PIC ZZ,ZZ9.99.
       01  WS-HALF-ED        PIC ZZ,ZZ9.9.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT AMT-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE AMT-FILE
           PERFORM SUMMARY-PARA
           STOP RUN.

       READ-PARA.
           READ AMT-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           ADD AR-AMT TO WS-WRAP-TOTAL
           ADD AR-AMT TO WS-SAFE-TOTAL
               ON SIZE ERROR
                   ADD 1 TO WS-OVERFLOWS
           END-ADD
           ADD 1 TO WS-COUNT
           COMPUTE WS-HALF = AR-AMT / 2
           MOVE AR-AMT TO WS-AMT-ED
           MOVE WS-WRAP-TOTAL TO WS-WRAP-ED
           MOVE WS-SAFE-TOTAL TO WS-SAFE-ED
           MOVE WS-HALF TO WS-HALF-ED
           DISPLAY AR-ACCT " " WS-AMT-ED " " WS-WRAP-ED " "
               WS-SAFE-ED " " WS-HALF-ED
           PERFORM READ-PARA.

       SUMMARY-PARA.
           DISPLAY "RECORDS: " WS-COUNT
           DISPLAY "OVERFLOWS: " WS-OVERFLOWS.