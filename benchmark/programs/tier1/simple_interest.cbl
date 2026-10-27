      * SIMPLE-INTEREST BATCH (tier 1)
      * Reads fixed-width loan records from input.dat and prints one
      * line per loan plus a summary. Written for this hackathon.
      * Record layout (21 bytes): ACCT X(6) | PRINCIPAL 9(7)V99 |
      *                           RATE 9(2)V99 (percent) | YEARS 9(2)
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIMPLEINT.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOAN-FILE ASSIGN TO "input.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  LOAN-FILE.
       01  LOAN-REC.
           05 LR-ACCT        PIC X(6).
           05 LR-PRINCIPAL   PIC 9(7)V99.
           05 LR-RATE        PIC 9(2)V99.
           05 LR-YEARS       PIC 9(2).

       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG       PIC X       VALUE "N".
           88 INPUT-DONE                 VALUE "Y".
       01  WS-INTEREST       PIC 9(9)V99 VALUE 0.
       01  WS-TOTAL          PIC 9(11)V99 VALUE 0.
       01  WS-COUNT          PIC 9(5)    VALUE 0.
       01  WS-PRIN-ED        PIC Z,ZZZ,ZZ9.99.
       01  WS-INT-ED         PIC ZZZ,ZZZ,ZZ9.99.
       01  WS-TOTAL-ED       PIC ZZ,ZZZ,ZZZ,ZZ9.99.

       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT LOAN-FILE
           PERFORM READ-PARA
           PERFORM PROCESS-PARA UNTIL INPUT-DONE
           CLOSE LOAN-FILE
           PERFORM SUMMARY-PARA
           STOP RUN.

       READ-PARA.
           READ LOAN-FILE
               AT END SET INPUT-DONE TO TRUE
           END-READ.

       PROCESS-PARA.
           COMPUTE WS-INTEREST ROUNDED =
               LR-PRINCIPAL * LR-RATE * LR-YEARS / 100
           ADD WS-INTEREST TO WS-TOTAL
           ADD 1 TO WS-COUNT
           MOVE LR-PRINCIPAL TO WS-PRIN-ED
           MOVE WS-INTEREST TO WS-INT-ED
           DISPLAY LR-ACCT " " WS-PRIN-ED " " WS-INT-ED
           PERFORM READ-PARA.

       SUMMARY-PARA.
           MOVE WS-TOTAL TO WS-TOTAL-ED
           DISPLAY "RECORDS: " WS-COUNT
           DISPLAY "TOTAL INTEREST: " WS-TOTAL-ED.
           